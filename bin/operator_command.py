import fix_path

from operator_command_base import OperatorCommandBase
from operator_command_licenses import OperatorCommandLicenses
from operator_command_splunk import OperatorCommandSplunk


class OperatorCommand(
        OperatorCommandLicenses,
        OperatorCommandSplunk,
        OperatorCommandBase,
):

    pass
