# Optimizers

[![Python3.12](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/downloads/)
![tests](https://github.com/facebookresearch/optimizers/actions/workflows/tests.yaml/badge.svg)
![gpu-tests](https://github.com/facebookresearch/optimizers/actions/workflows/gpu-tests.yaml/badge.svg)
![pre-commit](https://github.com/facebookresearch/optimizers/actions/workflows/pre-commit.yaml/badge.svg)
![type-checking](https://github.com/facebookresearch/optimizers/actions/workflows/type-check.yaml/badge.svg)
![examples](https://github.com/facebookresearch/optimizers/actions/workflows/examples.yaml/badge.svg)

*Copyright (c) Meta Platforms, Inc. and affiliates.
All rights reserved.*

## Description
Optimizers is a Github repository of PyTorch optimization algorithms. It is designed for external collaboration and development.

Currently includes the optimizers:
- Distributed Shampoo

See the [CONTRIBUTING](CONTRIBUTING.md) file for how to help out.

## License
Optimizers is BSD licensed, as found in the LICENSE file.

## Installation and Dependencies
This code requires `python>=3.12` and `torch>=2.5.0`.
Install `distributed_shampoo` with all dependencies:
```bash
git clone git@github.com:facebookresearch/optimizers.git
cd optimizers
pip install .
```
If you also want to try the [examples](./distributed_shampoo/examples/), replace the last line with `pip install ".[examples]"`.

## Usage

After installation, basic usage looks like:
```python
import torch
from distributed_shampoo import AdamGraftingConfig, DistributedShampoo

model = ...  # Instantiate model

optim = DistributedShampoo(
    model.parameters(),
    lr=1e-3,
    betas=(0.9, 0.999),
    epsilon=1e-8,
    grafting_config=AdamGraftingConfig(
        beta2=0.999,
        epsilon=1e-8,
    ),
)
```

For more, please see the [additional documentation here](./distributed_shampoo/README.md) and especially the [How to Use](./distributed_shampoo/README.md#how-to-use) section.
