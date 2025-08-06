# Installation

For the latest stable release:

```bash
pip install swe-rex
# With modal support
pip install 'swe-rex[modal]'
# With fargate support
pip install 'swe-rex[fargate]'
# Development setup (all optional dependencies)
pip install 'swe-rex[dev]'
```

For the latest development version:

```bash
git clone https://github.com/SWE-agent/swe-rex
cd swe-rex
pip install -e '.[dev]'
```

If you want to contribute, please also use [pre-commit](https://pre-commit.com/):

```bash
pre-commit install
```

{% include-markdown "_footer.md" %}
