# Preconditioner Benchmark

This benchmark compares different preconditioners vin [shampoo_preconditioner_list.py](https://github.com/facebookresearch/optimizers/blob/main/distributed_shampoo/utils/shampoo_preconditioner_list.py). It illustrate total time, time per epochs, and total memory-usage.

### Usage

```bash
uv run preconditioner_benchmark
```

### Benchmark List

- `SGDPreconditionerList` : SGD (no preconditioning)
- `AdagradPreconditionerList` : AdaGrad
- `RootInvShampooPreconditionerList` : Root Inverse Shampoo
- `EigendecomposedShampooPreconditionerList` : Eigendecomposed Shampoo
- `EigenvalueCorrectedShampooPreconditionerList` : Eigenvalue-Corrected Shampoo