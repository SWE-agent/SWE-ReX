<div align="center">
<a href="https://swe-rex.com"><img src="docs/assets/swe-rex-logo-bg.svg" alt="SWE-ReX" style="height: 10em"/></a>

# SWE-agent Remote Execution Framework

[👉 Read the documentation 👈](https://swe-rex.com)

[![Pytest](https://github.com/SWE-agent/swe-rex/actions/workflows/pytest.yaml/badge.svg)](https://github.com/SWE-agent/swe-rex/actions/workflows/pytest.yaml)
[![Check Markdown links](https://github.com/SWE-agent/swe-rex/actions/workflows/check-links.yaml/badge.svg)](https://github.com/SWE-agent/swe-rex/actions/workflows/check-links.yaml)
[![build-docs](https://github.com/SWE-agent/swe-rex/actions/workflows/build-docs.yaml/badge.svg)](https://github.com/SWE-agent/swe-rex/actions/workflows/build-docs.yaml)
</div>

SWE-ReX is a runtime interface for interacting with sandboxed shell environments, allowing you to effortlessly let your AI agent run *any command* on *any environment*.

Whether commands are executed locally or remotely in Docker containers, AWS remote machines, Modal, or something else, your agent code remains the same.
Running 100 agents in parallel? No problem either!

Specifically, SWE-ReX allows your agent to

* ✅ **Interact with running shell sessions**. SWE-ReX will recognize when commands are finished, extract the output and exit code and return them to your agent.
* ✅ Let your agent use **interactive command line tools** like `ipython`, `gdb` or more in the shell.
* ✅ Interact with **multiple such shell sessions in parallel**, similar to how humans can have a shell, ipython, gdb, etc. all running at the same time.

We built SWE-ReX to help you focus on developing and evaluating your agent, not on infrastructure.

SWE-ReX came out of our experiences with [SWE-agent][] and [SWE-agent enigma][enigma].
Using SWE-ReX, we

* 🦖 Support **fast, massively parallel** agent runs (which made evaluating on large benchmarks a breeze).
* 🦖 Support a **broad range of platforms**, including non-Linux machines without Docker.
* 🦖 **Disentangle agent logic from infrastructure concerns**, making SWE-agent more stable and easier to maintain.

This is [SWE-agent][] using SWE-ReX to run on 30 [SWE-bench][] instances in parallel:

<div align="center">
<img src="docs/assets/swerex.gif" alt="SWE-ReX in action" width=600px>
</div>

## Get started

```bash
pip install swe-rex
# With modal support
pip install 'swe-rex[modal]'
# With fargate support
pip install 'swe-rex[fargate]'
# With daytona support (WIP)
pip install 'swe-rex[daytona]'
# Development setup (all optional dependencies)
pip install 'swe-rex[dev]'
```

Then head over to [our documentation](https://swe-rex.com/) to learn more!


[SWE-agent]: https://swe-agent.com
[SWE-bench]: https://swebench.com
[enigma]: https://enigma-agent.com/

## Related projects

<div align="center">
  <a href="https://github.com/SWE-agent/SWE-agent"><img src="docs/assets/sweagent_logo_text_below.svg" alt="SWE-agent" height="120px"></a>
  <!-- <a href="https://github.com/SWE-agent/SWE-ReX"><img src="docs/assets/swerex_logo_text_below.svg" alt="SWE-ReX" height="120px"></a> -->
   &nbsp;&nbsp;
  <a href="https://github.com/SWE-bench/SWE-smith"><img src="docs/assets/swesmith_logo_text_below.svg" alt="SWE-smith" height="120px"></a>
   &nbsp;&nbsp;
  <a href="https://github.com/SWE-bench/SWE-bench"><img src="docs/assets/swebench_logo_text_below.svg" alt="SWE-bench" height="120px"></a>
  &nbsp;&nbsp;
  <a href="https://github.com/SWE-bench/sb-cli"><img src="docs/assets/sbcli_logo_text_below.svg" alt="sb-cli" height="120px"></a>
</div