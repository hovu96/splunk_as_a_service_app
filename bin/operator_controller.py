import fix_path
import sys
import traceback


def get_input_name(stack_id, command):
    if sys.platform == "win32":
        script_path = ".\\bin\\operator_main.py"
    else:
        script_path = "./bin/operator_main.py"
    return "%s %s %s" % (script_path, stack_id, command)


def run_command(service, stack_id, command, interval=60):
    service.inputs.create(
        name=get_input_name(stack_id, command),
        kind="script",
        interval=interval,
        source=stack_id,
        sourcetype="stack_operator",
        passAuth="admin",
    )


def stop_command(service, stack_id, command):
    try:
        service.inputs.delete(
            name=get_input_name(stack_id, command),
            kind="script",
        )
    except KeyError:
        pass


def start_operator(service, stack_id):
    run_command(service, stack_id, "up")


def stop_operator(service, stack_id, force=False):
    stop_command(service, stack_id, "up")
    stop_command(service, stack_id, "down")
    stop_command(service, stack_id, "kill")
    if force:
        run_command(service, stack_id, "kill")
    else:
        run_command(service, stack_id, "down")
