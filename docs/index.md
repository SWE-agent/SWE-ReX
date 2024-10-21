SWE-ReX is a runtime for interacting with sandboxed shell environments, allowing to effortlessly let your AI agent run anything from `ls` to interactive `pdb` sessions.
Whether commands are executed locally or remotely in docker containers, on AWS, modal, or something else, your code remains the same.

Let's take a look how it works:

1. Your central entry point is one of the [`Deployment` classes][abstractdeployment], depending on where your code should run. 
2. Your `Deployment` instances allows your to start your docker container, AWS instance, or whatever at the push of a button. That's right, no more fiddeling with the AWS console!
3. After the `Deployment` has started your container _somewhere_, you are handed a [`RemoteRuntime` instance][remoteruntime].
  This is your main interface for interacting with the environment. You can use it start new shell or interactive sessions, read and write files, execute one-off commands, etc.

[abstractdeployment]: deployments/#swerex.deployments.AbstractDeployment
[remoteruntime]: runtimes/#swerex.runtime.remote.RemoteRuntime
[localruntime]: runtimes/#swerex.runtime.local.Runtime
[server]: server/#swerex.server

![architecture](./assets/architecture.svg)

Looking closer at the internals:

4. Within the container, we have a fastapi [Server][server] that transfers all request from the [`RemoteRuntime`][remoteruntime] to the [`LocalRuntime`][localruntime].
   The [`LocalRuntime`][localruntime] has the exact same interface as the [`RemoteRuntime` class][remoteruntime] and it is what actually executes the commands.
   In fact, if you want to run something locally (or your whole codebase runs in a sandboxed environment), you can just use the [`LocalRuntime`][localruntime] directly!
   Both classes are absolutely interchangeable, in fact we even transfer any exceptions happening in the [`LocalRuntime`][localruntime] to the [`RemoteRuntime`][remoteruntime] transparently,
   so you can easily catch and ignore certain errors.

5. The [`Runtime`][abstractruntime] class provides several methods for reading/writing files, an [`execute` method][abstractruntime.execute] for running arbitrary commands, but the most important one is [`run_in_session`][abstractruntime.run_in_session].
   This method allows you to run a command in an existing shell session (or an interactive tool running inside of it) and return the output.
   In fact, you can have multiple sessions open at the same time, running different commands and tools in parallel!

[runtime]: runtimes/#swerex.runtime.abstract.Runtime
[abstractruntime]: runtimes/#swerex.runtime.abstract.AbstractRuntime
[abstractruntime.execute]: runtimes/#swerex.runtime.abstract.AbstractRuntime.execute
[abstractruntime.run_in_session]: runtimes/#swerex.runtime.abstract.AbstractRuntime.run_in_session
