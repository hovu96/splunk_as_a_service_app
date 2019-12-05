# Dependencies

## Kubernetes Libraries

Important:
Patched method for writing data into a pod stream (see stream/ws_client.py):

`
def write_channel(self, channel, data):
    """Write data to a channel."""
    # check if we're writing binary data or not
    binary = six.PY3 and type(data) == six.binary_type
    opcode = ABNF.OPCODE_BINARY if binary else ABNF.OPCODE_TEXT

    channel_prefix = chr(channel)
    if binary:
        channel_prefix = six.binary_type(channel_prefix, "ascii")

    payload = channel_prefix + data
    self.sock.send(payload, opcode=opcode)
`

When upgrading, check if https://github.com/kubernetes-client/python-base/pull/152/files is merged.

## Splunk Libraries
