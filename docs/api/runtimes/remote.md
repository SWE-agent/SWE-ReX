::: swerex.runtime.remote.RemoteRuntime

## File decoding errors

`read_file` keeps the requested `encoding` and `errors` semantics of `Path.read_text`.
Strict decoding failures remain catchable with `except UnicodeDecodeError`.

Remote errors transfer at most 4,096 bytes from the original decoder object. For
objects within that limit, the built-in exception's bytes, offsets, reason, and
message are preserved. For larger objects, the client raises
`swerex.exceptions.TruncatedUnicodeDecodeError`, a `UnicodeDecodeError` subclass.
Its message explicitly identifies truncated context; its `object` is a byte window,
not the complete original object. The window starts up to 128 bytes before the
first failing byte and includes at most 4,096 bytes in total.

For this subclass, `start` and `end` index the portion of the failure retained in
`object`. `original_start` and `original_end` preserve the original offsets;
`object_offset` gives the window's original offset and `object_length` gives the
original decoder object's byte length. All end offsets are exclusive. A failure
span longer than the window is clipped only for the window-relative `end`;
`original_end` remains unchanged. `encoding` and `reason` are unchanged, but `args`
and `str()` differ from the local error. No missing bytes are fabricated or decoded
with replacement. Applications needing the complete object must obtain it
separately rather than treating this exception's `object` as a full copy.

Malformed transport metadata retains the generic `SwerexException` fallback.
Older servers do not send the metadata and retain that fallback too; both endpoints
need the updated protocol to preserve the decode error type. Custom subclasses of
`UnicodeDecodeError` use the existing generic exception transport.
