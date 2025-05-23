"""
Copyright (c) Meta Platforms, Inc. and affiliates.
All rights reserved.

This source code is licensed under the BSD-style license found in the
LICENSE file in the root directory of this source tree.

"""

import itertools
import re
import unittest
import unittest.mock as mock
from collections.abc import Callable
from dataclasses import dataclass
from fractions import Fraction
from functools import partial
from types import ModuleType

import matrix_functions

import numpy as np

import torch
from matrix_functions import (
    _matrix_inverse_root_eigen,
    _matrix_inverse_root_newton,
    check_diagonal,
    compute_matrix_root_inverse_residuals,
    matrix_eigendecomposition,
    matrix_inverse_root,
    NewtonConvergenceFlag,
)
from matrix_functions_types import (
    CoupledHigherOrderConfig,
    CoupledNewtonConfig,
    DefaultEigendecompositionConfig,
    EigenConfig,
    EigendecompositionConfig,
    EighEigendecompositionConfig,
    QREigendecompositionConfig,
    RootInvConfig,
)
from torch import Tensor
from torch.testing._internal.common_utils import (
    instantiate_parametrized_tests,
    parametrize,
)


class CheckDiagonalTest(unittest.TestCase):
    def test_check_diagonal_for_not_two_dim_matrix(self) -> None:
        A = torch.zeros((2, 2, 2))
        self.assertRaisesRegex(
            ValueError, re.escape("Matrix is not 2-dimensional!"), check_diagonal, A
        )

    def test_check_diagonal_for_not_square_matrix(self) -> None:
        A = torch.zeros((2, 3))
        self.assertRaisesRegex(
            ValueError, re.escape("Matrix is not square!"), check_diagonal, A
        )

    def test_check_diagonal_for_diagonal_matrix(self) -> None:
        A = torch.eye(2)
        self.assertTrue(check_diagonal(A))


@instantiate_parametrized_tests
class MatrixInverseRootTest(unittest.TestCase):
    def test_matrix_inverse_root_scalar(self) -> None:
        A = torch.tensor(2.0)
        root = 2.0
        exp = 1.82
        with self.subTest("Test with scalar case."):
            self.assertEqual(
                A ** torch.tensor(-exp / root),
                matrix_inverse_root(
                    A,
                    root=Fraction(root / exp),
                ),
            )
        with self.subTest("Test with matrix case."):
            self.assertEqual(
                torch.tensor([[A ** torch.tensor(-exp / root)]]),
                matrix_inverse_root(
                    torch.tensor([[A]]),
                    root=Fraction(root / exp),
                ),
            )

    def test_matrix_inverse_root_with_not_two_dim_matrix(self) -> None:
        A = torch.zeros((1, 2, 3))
        root = Fraction(4)
        self.assertRaisesRegex(
            ValueError,
            re.escape("Matrix is not 2-dimensional!"),
            matrix_inverse_root,
            A=A,
            root=root,
            is_diagonal=False,
        )

    def test_matrix_inverse_root_not_square(self) -> None:
        A = torch.zeros((2, 3))
        root = Fraction(4)
        self.assertRaisesRegex(
            ValueError,
            re.escape("Matrix is not square!"),
            matrix_inverse_root,
            A=A,
            root=root,
            is_diagonal=False,
        )

    @parametrize(
        "root_inv_config",
        (
            EigenConfig(),
            CoupledNewtonConfig(),
            EigenConfig(enhance_stability=True),
            EigenConfig(eigendecomposition_offload_device="cpu"),
            *(CoupledHigherOrderConfig(order=order) for order in range(2, 7)),
        ),
    )
    @parametrize("exp", (1, 2))
    @parametrize(
        "A, expected_root",
        (
            # A diagonal matrix.
            (
                torch.tensor([[1.0, 0.0], [0.0, 4.0]]),
                torch.tensor([[1.0, 0.0], [0.0, 0.5]]),
            ),
            # Non-diagonal matrix.
            (
                torch.tensor(
                    [
                        [1195.0, -944.0, -224.0],
                        [-944.0, 746.0, 177.0],
                        [-224.0, 177.0, 42.0],
                    ]
                ),
                torch.tensor([[1.0, 1.0, 1.0], [1.0, 2.0, -3.0], [1.0, -3.0, 18.0]]),
            ),
        ),
    )
    def test_matrix_inverse_root(
        self, A: Tensor, expected_root: Tensor, exp: int, root_inv_config: RootInvConfig
    ) -> None:
        atol = 0.05
        rtol = 1e-2

        torch.testing.assert_close(
            torch.linalg.matrix_power(expected_root, exp),
            matrix_inverse_root(
                A=A,
                root=Fraction(2, exp),
                is_diagonal=False,
                root_inv_config=root_inv_config,
            ),
            atol=atol,
            rtol=rtol,
        )

    def test_matrix_inverse_root_higher_order_blowup(self) -> None:
        A = torch.tensor([[1.0, 0.0], [0.0, 1e-4]])
        self.assertRaisesRegex(
            ArithmeticError,
            re.escape(
                "NaN/Inf in matrix inverse root (after powering for fractions), raising an exception!"
            ),
            matrix_inverse_root,
            A=A,
            root=Fraction(1, 20),
            root_inv_config=CoupledHigherOrderConfig(),
        )

    def test_matrix_inverse_root_with_no_effect_exponent_multiplier(self) -> None:
        A = torch.tensor([[1.0, 0.0], [0.0, 4.0]])
        exp = 3
        self.assertRaisesRegex(
            ValueError,
            re.escape(
                f"root.denominator={exp} must be equal to 1 to use coupled inverse Newton iteration!"
            ),
            matrix_inverse_root,
            A=A,
            root=Fraction(2, exp),
            root_inv_config=CoupledNewtonConfig(),
        )

    @parametrize(
        "root_inv_config, implementation, msg",
        [
            (CoupledNewtonConfig(), "_matrix_inverse_root_newton", "Newton"),
            (
                CoupledHigherOrderConfig(),
                "_matrix_inverse_root_higher_order",
                "Higher order method",
            ),
        ],
    )
    def test_matrix_inverse_root_reach_max_iterations(
        self, root_inv_config: RootInvConfig, implementation: str, msg: str
    ) -> None:
        A = torch.tensor([[1.0, 0.0], [0.0, 4.0]])
        root = Fraction(4)
        with mock.patch.object(
            matrix_functions,
            implementation,
            return_value=(
                None,
                None,
                NewtonConvergenceFlag.REACHED_MAX_ITERS,
                None,
                None,
            ),
        ), self.assertLogs(
            level="WARNING",
        ) as cm:
            matrix_inverse_root(
                A=A,
                root=root,
                root_inv_config=root_inv_config,
            )
            self.assertIn(
                f"{msg} did not converge and reached maximum number of iterations!",
                [r.msg for r in cm.records],
            )

    def test_matrix_inverse_root_higher_order_tf32_preservation(self) -> None:
        A = torch.tensor([[1.0, 0.0], [0.0, float("inf")]])
        root = Fraction(2)
        tf32_flag_before = torch.backends.cuda.matmul.allow_tf32
        self.assertRaisesRegex(
            ArithmeticError,
            re.escape("Input matrix has entries close to inf"),
            matrix_inverse_root,
            A=A,
            root=root,
            root_inv_config=CoupledHigherOrderConfig(),
        )
        tf32_flag_after = torch.backends.cuda.matmul.allow_tf32
        self.assertEqual(tf32_flag_before, tf32_flag_after)

    def test_matrix_inverse_root_higher_order_error_blowup_before_powering(
        self,
    ) -> None:
        # Trigger this error by using an ill-conditioned matrix.
        A = torch.tensor([[1.0, 0.0], [0.0, 1e-4]])
        root = Fraction(2)
        self.assertRaisesRegex(
            ArithmeticError,
            r"Error in matrix inverse root \(before powering for fractions\) [+-]?([0-9]*[.])?[0-9]+ exceeds threshold 1e-1, raising an exception!",
            matrix_inverse_root,
            A=A,
            root=root,
            # Set max_iterations to 0 to fast forward to the error check before powering.
            root_inv_config=CoupledHigherOrderConfig(max_iterations=0),
        )

    def test_matrix_inverse_root_with_invalid_root_inv_config(self) -> None:
        @dataclass
        class NotSupportedRootInvConfig(RootInvConfig):
            """A dummy root inv config that is not supported."""

            unsupported_root: int = -1

        A = torch.tensor([[1.0, 0.0], [0.0, 4.0]])
        root = Fraction(4)
        self.assertRaisesRegex(
            NotImplementedError,
            r"Root inverse config is not implemented! Specified root inverse config is root_inv_config=.*\.NotSupportedRootInvConfig\(.*\)\.",
            matrix_inverse_root,
            A=A,
            root=root,
            root_inv_config=NotSupportedRootInvConfig(),
            is_diagonal=False,
        )


@instantiate_parametrized_tests
class MatrixRootDiagonalTest(unittest.TestCase):
    @parametrize("root", (-1, 0))
    def test_matrix_root_diagonal_nonpositive_root(self, root: int) -> None:
        A = torch.tensor([[-1.0, 0.0], [0.0, 2.0]])
        self.assertRaisesRegex(
            ValueError,
            re.escape(f"Root {root} should be positive!"),
            matrix_inverse_root,
            A=A,
            root=root,
            is_diagonal=True,
        )

    def test_matrix_root(self) -> None:
        A = torch.tensor([[1.0, 0.0], [0.0, 4.0]])
        root = Fraction(2)
        expected_root_list = torch.tensor([[1.0, 0.0], [0.0, 0.5]])

        torch.testing.assert_close(
            expected_root_list,
            matrix_inverse_root(
                A,
                root=root,
                is_diagonal=True,
            ),
        )


@instantiate_parametrized_tests
class EigenRootTest(unittest.TestCase):
    def _test_eigen_root_multi_dim(
        self,
        A: Callable[[int], Tensor],
        n: int,
        root: int,
        epsilon: float,
        tolerance: float,
        eig_sols: Callable[[int], Tensor],
    ) -> None:
        X, L, Q = _matrix_inverse_root_eigen(
            A=A(n),
            root=Fraction(root),
            epsilon=epsilon,
        )
        abs_error = torch.dist(torch.linalg.matrix_power(X, -root), A(n), p=torch.inf)
        A_norm = torch.linalg.norm(A(n), ord=torch.inf)
        rel_error = abs_error / torch.maximum(torch.tensor(1.0), A_norm)
        torch.testing.assert_close(L, eig_sols(n))
        self.assertLessEqual(rel_error.item(), tolerance)

    @parametrize("epsilon", [0.0])
    @parametrize("root", [1, 2, 4, 8])
    @parametrize("n", [10, 100])
    def test_eigen_root_identity(self, n: int, root: int, epsilon: float) -> None:
        self._test_eigen_root_multi_dim(
            A=torch.eye,
            n=n,
            root=root,
            epsilon=epsilon,
            tolerance=1e-6,
            eig_sols=torch.ones,
        )

    @parametrize(  # type: ignore
        "alpha, beta",
        [
            (alpha, beta)
            for alpha, beta in itertools.product(
                (0.001, 0.01, 0.1, 1.0, 10.0, 100.0), repeat=2
            )
            if 2 * beta <= alpha
        ],
    )
    @parametrize("epsilon", [0.0])
    @parametrize("root", [1, 2, 4, 8])
    @parametrize("n", [10, 100])
    def test_eigen_root_tridiagonal(
        self, n: int, root: int, epsilon: float, alpha: float, beta: float
    ) -> None:
        def eig_sols_tridiagonal_1(n: int, alpha: float, beta: float) -> Tensor:
            eigs = alpha * torch.ones(n) + 2 * beta * torch.tensor(
                [np.cos(j * torch.pi / n) for j in range(n)], dtype=torch.float
            )
            eigs, _ = torch.sort(eigs)
            return eigs

        def A_tridiagonal_1(n: int, alpha: float, beta: float) -> Tensor:
            diag = alpha * torch.ones(n)
            diag[0] += beta
            diag[n - 1] += beta
            off_diag = beta * torch.ones(n - 1)
            return (
                torch.diag(diag)
                + torch.diag(off_diag, diagonal=1)
                + torch.diag(off_diag, diagonal=-1)
            )

        self._test_eigen_root_multi_dim(
            A=partial(A_tridiagonal_1, alpha=alpha, beta=beta),
            n=n,
            root=root,
            epsilon=epsilon,
            tolerance=1e-4,
            eig_sols=partial(eig_sols_tridiagonal_1, alpha=alpha, beta=beta),
        )

        def eig_sols_tridiagonal_2(n: int, alpha: float, beta: float) -> Tensor:
            eigs = alpha * torch.ones(n) + 2 * beta * torch.tensor(
                [np.cos(2 * j * torch.pi / (2 * n + 1)) for j in range(1, n + 1)],
                dtype=torch.float,
            )
            eigs, _ = torch.sort(eigs)
            return eigs

        def A_tridiagonal_2(n: int, alpha: float, beta: float) -> Tensor:
            diag = alpha * torch.ones(n)
            diag[0] -= beta
            off_diag = beta * torch.ones(n - 1)
            return (
                torch.diag(diag)
                + torch.diag(off_diag, diagonal=1)
                + torch.diag(off_diag, diagonal=-1)
            )

        self._test_eigen_root_multi_dim(
            A=partial(A_tridiagonal_2, alpha=alpha, beta=beta),
            n=n,
            root=root,
            epsilon=epsilon,
            tolerance=1e-4,
            eig_sols=partial(eig_sols_tridiagonal_2, alpha=alpha, beta=beta),
        )

    def test_matrix_root_eigen_nonpositive_root(self) -> None:
        A = torch.tensor([[-1.0, 0.0], [0.0, 2.0]])
        root = -1
        self.assertRaisesRegex(
            ValueError,
            re.escape(f"Root {root} should be positive!"),
            matrix_inverse_root,
            A=A,
            root=root,
        )

    torch_linalg_module: ModuleType = torch.linalg

    @mock.patch.object(
        torch_linalg_module, "eigh", side_effect=RuntimeError("Mock Eigen Error")
    )
    def test_no_retry_double_precision_raise_exception(
        self, mock_eigh: mock.Mock
    ) -> None:
        A = torch.tensor([[-1.0, 0.0], [0.0, 2.0]])
        self.assertRaisesRegex(
            RuntimeError,
            re.escape("Mock Eigen Error"),
            matrix_inverse_root,
            A=A,
            root=Fraction(2),
            root_inv_config=EigenConfig(retry_double_precision=False),
            epsilon=0.0,
        )
        mock_eigh.assert_called_once()

    @mock.patch.object(
        torch_linalg_module, "eigh", side_effect=RuntimeError("Mock Eigen Error")
    )
    def test_retry_double_precision_raise_exception(self, mock_eigh: mock.Mock) -> None:
        A = torch.tensor([[-1.0, 0.0], [0.0, 2.0]])
        self.assertRaisesRegex(
            RuntimeError,
            re.escape("Mock Eigen Error"),
            matrix_inverse_root,
            A=A,
            root=Fraction(2),
            epsilon=0.0,
        )
        mock_eigh.assert_called()
        self.assertEqual(mock_eigh.call_count, 2)

    @mock.patch.object(
        torch_linalg_module,
        "eigh",
        side_effect=[
            RuntimeError("Mock Eigen Error"),
            (torch.ones(2), torch.eye(2)),
        ],
    )
    def test_retry_double_precision_double_precision(
        self, mock_eigh: mock.Mock
    ) -> None:
        A = torch.tensor([[1.0, 0.0], [0.0, 1.0]])
        X = matrix_inverse_root(
            A=A,
            root=Fraction(2),
            epsilon=0.0,
        )
        torch.testing.assert_close(X, torch.eye(2))
        mock_eigh.assert_called()
        self.assertEqual(mock_eigh.call_count, 2)


@instantiate_parametrized_tests
class NewtonRootInverseTest(unittest.TestCase):
    def _test_newton_root_inverse_multi_dim(
        self,
        A: Callable[[int], Tensor],
        n: int,
        root: int,
        epsilon: float,
        max_iterations: int,
        A_tol: float,
        M_tol: float,
    ) -> None:
        X, _, _, _, M_error = _matrix_inverse_root_newton(
            A(n), root, epsilon, max_iterations, M_tol
        )
        abs_A_error = torch.dist(torch.linalg.matrix_power(X, -root), A(n), p=torch.inf)
        A_norm = torch.linalg.norm(A(n), ord=torch.inf)
        rel_A_error = abs_A_error / torch.maximum(torch.tensor(1.0), A_norm)
        self.assertLessEqual(M_error.item(), M_tol)
        self.assertLessEqual(rel_A_error.item(), A_tol)

    @parametrize("epsilon", [0.0])
    @parametrize("root", [2, 4, 8])
    @parametrize("n", [10, 100])
    def test_newton_root_inverse_identity(
        self, n: int, root: int, epsilon: float
    ) -> None:
        max_iterations = 1000

        self._test_newton_root_inverse_multi_dim(
            A=torch.eye,
            n=n,
            root=root,
            epsilon=epsilon,
            max_iterations=max_iterations,
            A_tol=1e-6,
            M_tol=1e-6,
        )

    @parametrize(  # type: ignore
        "alpha, beta",
        [
            (alpha, beta)
            for alpha, beta in itertools.product(
                (0.001, 0.01, 0.1, 1.0, 10.0, 100.0), repeat=2
            )
            if 2 * beta <= alpha
        ],
    )
    @parametrize("epsilon", [0.0])
    @parametrize("root", [2, 4, 8])
    @parametrize("n", [10, 100])
    def test_newton_root_inverse_tridiagonal(
        self, n: int, root: int, epsilon: float, alpha: float, beta: float
    ) -> None:
        max_iterations = 1000

        def A_tridiagonal_1(n: int, alpha: float, beta: float) -> Tensor:
            diag = alpha * torch.ones(n)
            diag[0] += beta
            diag[n - 1] += beta
            off_diag = beta * torch.ones(n - 1)
            return (
                torch.diag(diag)
                + torch.diag(off_diag, diagonal=1)
                + torch.diag(off_diag, diagonal=-1)
            )

        self._test_newton_root_inverse_multi_dim(
            A=partial(A_tridiagonal_1, alpha=alpha, beta=beta),
            n=n,
            root=root,
            epsilon=epsilon,
            max_iterations=max_iterations,
            A_tol=1e-4,
            M_tol=1e-6,
        )

        def A_tridiagonal_2(n: int, alpha: float, beta: float) -> Tensor:
            diag = alpha * torch.ones(n)
            diag[0] -= beta
            off_diag = beta * torch.ones(n - 1)
            return (
                torch.diag(diag)
                + torch.diag(off_diag, diagonal=1)
                + torch.diag(off_diag, diagonal=-1)
            )

        self._test_newton_root_inverse_multi_dim(
            A=partial(A_tridiagonal_2, alpha=alpha, beta=beta),
            n=n,
            root=root,
            epsilon=epsilon,
            max_iterations=max_iterations,
            A_tol=1e-4,
            M_tol=1e-6,
        )


class CoupledHigherOrderRootInverseTest(unittest.TestCase):
    def test_root_with_big_numerator_denominator(self) -> None:
        A = torch.tensor([[1.0, 0.0], [0.0, 4.0]])
        root = Fraction(13, 15)
        with self.assertLogs(
            level="WARNING",
        ) as cm:
            matrix_inverse_root(
                A=A,
                root=root,
                root_inv_config=CoupledHigherOrderConfig(),
            )
        self.assertIn(
            "abs(root.numerator)=13 and abs(root.denominator)=15 are probably too big for best performance.",
            [r.msg for r in cm.records],
        )


@instantiate_parametrized_tests
class ComputeMatrixRootInverseResidualsTest(unittest.TestCase):
    def test_matrix_root_inverse_residuals_with_not_two_dim_matrix(self) -> None:
        A = torch.zeros((1, 2, 3))
        X_hat = torch.zeros((2, 2))
        root = Fraction(4)
        self.assertRaisesRegex(
            ValueError,
            re.escape("Matrix is not 2-dimensional!"),
            compute_matrix_root_inverse_residuals,
            A=A,
            X_hat=X_hat,
            root=root,
            epsilon=0.0,
        )

    def test_matrix_root_inverse_residuals_with_not_square_matrix(self) -> None:
        A = torch.zeros((1, 2))
        X_hat = torch.zeros((2, 2))
        root = Fraction(4)
        self.assertRaisesRegex(
            ValueError,
            re.escape("Matrix is not square!"),
            compute_matrix_root_inverse_residuals,
            A=A,
            X_hat=X_hat,
            root=root,
            epsilon=0.0,
        )

    def test_matrix_root_inverse_residuals_with_inconsistent_dims(self) -> None:
        A = torch.zeros((2, 2))
        X_hat = torch.zeros((3, 3))
        root = Fraction(4)
        self.assertRaisesRegex(
            ValueError,
            re.escape("Matrix shapes do not match!"),
            compute_matrix_root_inverse_residuals,
            A=A,
            X_hat=X_hat,
            root=root,
            epsilon=0.0,
        )

    @parametrize("root", (Fraction(2, 1), Fraction(4, 2)))
    def test_matrix_root_inverse_residuals(self, root: Fraction) -> None:
        A = torch.eye(2)
        X_hat = torch.eye(2)
        expected_relative_error = torch.tensor(0.0, dtype=torch.float64)
        expected_relative_residual = torch.tensor(0.0, dtype=torch.float64)

        (
            actual_relative_error,
            actual_relative_residual,
        ) = compute_matrix_root_inverse_residuals(
            A=A,
            X_hat=X_hat,
            root=root,
            epsilon=0.0,
        )
        torch.testing.assert_close(
            actual_relative_error,
            expected_relative_error,
        )
        torch.testing.assert_close(
            actual_relative_residual,
            expected_relative_residual,
        )


@instantiate_parametrized_tests
class MatrixEigendecompositionTest(unittest.TestCase):
    def test_matrix_eigendecomposition_scalar(self) -> None:
        A = torch.tensor(2.0)
        with self.subTest("Test with scalar case."):
            self.assertEqual(
                (A, torch.tensor(1)),
                matrix_eigendecomposition(A),
            )
        with self.subTest("Test with matrix case."):
            self.assertEqual(
                (torch.tensor([[A]]), torch.tensor([[1]])),
                matrix_eigendecomposition(torch.tensor([[A]])),
            )

    def test_matrix_eigendecomposition_with_not_two_dim_matrix(self) -> None:
        A = torch.zeros((1, 2, 3))
        self.assertRaisesRegex(
            ValueError,
            re.escape("Matrix is not 2-dimensional!"),
            matrix_eigendecomposition,
            A=A,
        )

    def test_matrix_eigendecomposition_not_square(self) -> None:
        A = torch.zeros((2, 3))
        self.assertRaisesRegex(
            ValueError,
            re.escape("Matrix is not square!"),
            matrix_eigendecomposition,
            A=A,
        )

    @parametrize(
        "eigendecomposition_config",
        (
            DefaultEigendecompositionConfig,
            EighEigendecompositionConfig(eigendecomposition_offload_device="cpu"),
        ),
    )
    @parametrize(
        "A, expected_eigenvalues, expected_eigenvectors",
        (
            # A diagonal matrix.
            (
                torch.tensor([[1.0, 0.0], [0.0, 4.0]]),
                torch.tensor([1.0, 4.0]),
                torch.tensor([[1.0, 0.0], [0.0, 1.0]]),
            ),
            # Non-diagonal matrix.
            (
                torch.tensor(
                    [
                        [1195.0, -944.0, -224.0],
                        [-944.0, 746.0, 177.0],
                        [-224.0, 177.0, 42.0],
                    ]
                ),
                torch.tensor([2.9008677229e-03, 1.7424316704e-01, 1.9828229980e03]),
                torch.tensor(
                    [
                        [0.0460073575, -0.6286827326, 0.7762997746],
                        [-0.1751257628, -0.7701635957, -0.6133345366],
                        [0.9834705591, -0.1077321917, -0.1455317289],
                    ]
                ),
            ),
        ),
    )
    def test_matrix_eigendecomposition(
        self,
        A: Tensor,
        expected_eigenvalues: Tensor,
        expected_eigenvectors: Tensor,
        eigendecomposition_config: EigendecompositionConfig,
    ) -> None:
        atol = 1e-4
        rtol = 1e-5

        torch.testing.assert_close(
            (expected_eigenvalues, expected_eigenvectors),
            matrix_eigendecomposition(
                A,
                eigendecomposition_config=eigendecomposition_config,
                is_diagonal=False,
            ),
            atol=atol,
            rtol=rtol,
        )

    @parametrize(
        "initialization_fn",
        (
            lambda A: torch.zeros_like(A),
            lambda A: torch.eye(A.shape[0], dtype=A.dtype, device=A.device),
            lambda A: matrix_eigendecomposition(A)[1],
        ),
    )
    @parametrize(
        "A, expected_eigenvalues, expected_eigenvectors",
        (
            # A diagonal matrix.
            (
                torch.tensor([[1.0, 0.0], [0.0, 4.0]]),
                torch.tensor([1.0, 4.0]),
                torch.tensor([[1.0, 0.0], [0.0, 1.0]]),
            ),
            # Non-diagonal matrix.
            (
                torch.tensor(
                    [
                        [1195.0, -944.0, -224.0],
                        [-944.0, 746.0, 177.0],
                        [-224.0, 177.0, 42.0],
                    ]
                ),
                torch.tensor([2.9008677229e-03, 1.7424316704e-01, 1.9828229980e03]),
                torch.tensor(
                    [
                        [0.0460073575, -0.6286827326, 0.7762997746],
                        [-0.1751257628, -0.7701635957, -0.6133345366],
                        [0.9834705591, -0.1077321917, -0.1455317289],
                    ]
                ),
            ),
        ),
    )
    def test_matrix_eigendecomposition_with_qr(
        self,
        A: Tensor,
        expected_eigenvalues: Tensor,
        expected_eigenvectors: Tensor,
        initialization_fn: Callable[[Tensor], Tensor],
    ) -> None:
        atol = 2e-3
        rtol = 1e-5

        qr_config = QREigendecompositionConfig(max_iterations=10_000)
        qr_config.eigenvectors_estimate = initialization_fn(A)
        estimated_eigenvalues, estimated_eigenvectors = matrix_eigendecomposition(
            A,
            is_diagonal=False,
            eigendecomposition_config=qr_config,
        )

        # Ensure that the signs of the eigenvectors are consistent.
        estimated_eigenvectors[
            :,
            expected_eigenvectors[0, :] / estimated_eigenvectors[0, :] < 0,
        ] *= -1
        torch.testing.assert_close(
            (expected_eigenvalues, expected_eigenvectors),
            (estimated_eigenvalues, estimated_eigenvectors),
            atol=atol,
            rtol=rtol,
        )

    def test_invalid_eigendecomposition_config(self) -> None:
        @dataclass
        class NotSupportedEigendecompositionConfig(EigendecompositionConfig):
            """A dummy class eigendecomposition config that is not supported."""

            unsupoorted_field: int = 0

        self.assertRaisesRegex(
            NotImplementedError,
            r"Eigendecomposition config is not implemented! Specified eigendecomposition config is eigendecomposition_config=.*\.NotSupportedEigendecompositionConfig\(.*\).",
            matrix_eigendecomposition,
            A=torch.tensor([[1.0, 0.0], [0.0, 4.0]]),
            eigendecomposition_config=NotSupportedEigendecompositionConfig(),
        )


class MatrixEigendecompositionDiagonalTest(unittest.TestCase):
    def test_matrix_eigendecomposition(self) -> None:
        A = torch.tensor([[1.0, 0.0], [0.0, 4.0]])
        expected_eigenvalues, expected_eigenvectors = (
            torch.tensor([1.0, 4.0]),
            torch.tensor([[1.0, 0.0], [0.0, 1.0]]),
        )

        torch.testing.assert_close(
            (expected_eigenvalues, expected_eigenvectors),
            matrix_eigendecomposition(
                A,
                is_diagonal=True,
            ),
        )
