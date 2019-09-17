import fix_path

from operator_command_base import OperatorCommandBase
from operator_command_licenses import OperatorCommandLicenses
from operator_command_splunk import OperatorCommandSplunk
from operator_command_apps import OperatorCommandApps


class OperatorCommand(
        OperatorCommandApps,
        OperatorCommandLicenses,
        OperatorCommandSplunk,
        OperatorCommandBase,
):

    pass
