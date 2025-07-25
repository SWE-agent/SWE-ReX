# Tutorial

Here are a few examples of how to use SWE-ReX.

## Hello world from your own machine

!!! warning
    This first example will run commands on your local machine _without_ any sandboxing, so don't `rm -rf /`!
    Wait for the next example to see how to put it in a sandbox ;) 

!!! note
    SWE-ReX is inherently asynchronous, so you might want to take a quick look at python's `asyncio` module before continuing (or click the :material-chevron-right-circle: icons in the next example).

```python
import asyncio
from swerex.deployment.local import LocalDeployment
from swerex.runtime.abstract import CreateBashSessionRequest, BashAction, Command

deployment = LocalDeployment()

async def run_some_stuff(deployment):
    """Spoiler: This function will work with any deployment."""
    await deployment.start()  # (1)!
    runtime = deployment.runtime

    # Issue a few one-off commands, similar to `subprocess.run()`
    print(await runtime.execute(Command(command=["echo", "Hello, world!"])))

    # Create a bash session
    await runtime.create_session(CreateBashSessionRequest())

    # Run a command in the session
    # The difference to the one-off commands is that environment state persists!
    print(await runtime.run_in_session(BashAction(command="export MYVAR='test'")))
    print(await runtime.run_in_session(BashAction(command="echo $MYVAR")))

    await deployment.stop()  # (2)!

asyncio.run(run_some_stuff(deployment))  # (3)!
```

1. In the case of a `LocalDeployment`, this won't do much. However, if you run in a docker container or similar, this will for example pull the container image and start the runtime in it. The `await` will wait until the runtime has been started.

2. Again, this won't do much in the case of a `LocalDeployment`, but it will kill docker containers or similar when used with the appropriate deployment.

3. Since this is an async function, we need to call it with `asyncio.run()` when not running in another async function.

## Our first "remote" run

The best thing about SWE-ReX is that you can switch between deployments without any changes to your code!
We will simply use the same `run_some_stuff` function but change the deployment to a `DockerDeployment`:

```python
from swerex.deployment.docker import DockerDeployment

deployment = DockerDeployment(image="python:3.12")
asyncio.run(run_some_stuff(deployment))
```

You should see the following output:

```
🦖 DEBUG    Ensuring deployment is stopped because object is deleted
🦖 INFO     Pulling image 'python:3.12'
🦖 DEBUG    Found free port 59647
🦖 INFO     Starting container python3.12-608e9964-2a5e-409b-a7b7-52b520034068 with image python:3.12 serving on port 59647
🦖 DEBUG    Command: "docker run --rm -p 59647:8000 --name python3.12-608e9964-2a5e-409b-a7b7-52b520034068 python:3.12 /bin/sh -c 'swerex-remote --auth-token 1d87776a-1ab2-422e-bd80-fc34d810633f || (python3 -m pip install pipx && python3 -m pipx ensurepath && pipx run
            0fdb5604 --auth-token 1d87776a-1ab2-422e-bd80-fc34d810633f)'"
🦖 INFO     Starting runtime at 59647
🦖 INFO     Runtime started in 18.78s
stdout='Hello, world!\n' stderr='' exit_code=0
output='' exit_code=0 failure_reason='' expect_string='SHELLPS1PREFIX' session_type='bash'
output='test' exit_code=0 failure_reason='' expect_string='SHELLPS1PREFIX' session_type='bash'
```

So what's going on here? There's multiple steps:

1. We pull the `python:3.12` image from Docker Hub and start a container from it.
2. We run `swerex-remote` in the container. It is installed by `pipx` in a virtual environment, so it will not pollute your global Python environment. This is a small server that will wait for commands from SWE-ReX. Fun fact, this will basically run the `LocalRuntime` which was started by the `LocalDeployment` in the previous example.
3. `DockerDeployment` starts a `RemoteRuntime` that connects to the `swerex-remote` server in the container and executes your commands.

## Running with Modal

Similarly, you can also create remote runs on [Modal](https://modal.com) by swapping out the `DockerDeployment` with `ModalDeployment`.

```python
from swerex.deployment.modal import ModalDeployment

async def run_modal_deployment():
    deployment = ModalDeployment(
        image="python:3.12",
        startup_timeout=60, # wait 1 minute for deployment to start
        deployment_timeout=3600, # kill deployment after 1 hour
    )
    await deployment.start()
    await deployment.is_alive()
    return deployment

deployment = asyncio.run(run_modal_deployment())
asyncio.run(run_some_stuff(deployment))
```

You should see the following output:

```
🦖 INFO     Building image from docker registry python:3.12
🦖 INFO     Starting modal sandbox
🦖 INFO     Sandbox (sb-[ID]) created in 0.91s
🦖 INFO     Check sandbox logs at [MODAL_APP_LOGS_URL]
🦖 INFO     Sandbox created with id sb-[ID]
🦖 INFO     Starting runtime at [MODAL_HOST_URL]   
🦖 INFO     Runtime started in 10.46s
🦖 INFO     Starting modal sandbox
🦖 INFO     Sandbox (sb-[ID]) created in 1.17s
🦖 INFO     Check sandbox logs at [MODAL_APP_LOGS_URL]  
🦖 INFO     Sandbox created with id sb-[ID]
🦖 INFO     Starting runtime at [MODAL_HOST_URL]
🦖 INFO     Runtime started in 10.80s                                       
stdout='Hello, world!\n' stderr='' exit_code=0
output='' exit_code=0 failure_reason='' expect_string='SHELLPS1PREFIX' session_type='bash'
output='test\n' exit_code=0 failure_reason='' expect_string='SHELLPS1PREFIX' session_type='bash'
🦖 DEBUG    Ensuring deployment is stopped because object is deleted          
```