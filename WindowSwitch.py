import os, console, sys, ctypes
from common import expand_env_vars
import PyCmdUtils

windows_state_path = 'win_stat.txt'
winstate_separator = '^$^'

pycmd_data_dir = None
winstate_full_path = None

def py_GetConsoleWindow():
    return ctypes.windll.kernel32.GetConsoleWindow()

def py_IsWindow(hwnd):
    return ctypes.windll.user32.IsWindow(hwnd)

def init():
    # %APPDATA% is not always defined (e.g. when using runas.exe)
    if 'APPDATA' in os.environ.keys():
        APPDATA = '%APPDATA%'
    else:
        APPDATA = '%USERPROFILE%\\Application Data'

    global pycmd_data_dir
    global winstate_full_path

    pycmd_data_dir = expand_env_vars(APPDATA + '\\PyCmd')
    winstate_full_path = os.path.join(pycmd_data_dir, windows_state_path)

    if not os.path.exists(winstate_full_path):
        open(winstate_full_path, 'a').close()

def update_window_state(hwnd, pwd = '', cmd = '', remove_hwnd_list=[]):
    """Update status for given hwnd"""
    
    pwd = pwd.strip()
    cmd = cmd.strip()
    remove_hwnd = len(pwd) == 0 and len(cmd) == 0

    if not remove_hwnd and len(pwd) == 0:
        pwd = os.getcwd()

    with open(winstate_full_path, 'r+') as f:
        winstate = f.readlines()
        f.seek(0)

        for line in winstate:
            stats = line.split(winstate_separator)
            if int(stats[0]) in remove_hwnd_list:
                # remove invalid line
                continue
            if not line.startswith(str(hwnd)):
                f.write(line)
            elif not remove_hwnd:
                if len(stats) != 3:
                    print("Warning: unsupported line for windows switch", line)
                if len(cmd) == 0:
                    cmd = stats[2]
        if not remove_hwnd:
            new_line = winstate_separator.join([str(hwnd), pwd, cmd]) + '\n'
            f.write(new_line)
        f.truncate()

def list_and_switch():
    winstate_full_path = os.path.join(pycmd_data_dir, windows_state_path)
    with open(winstate_full_path, 'r') as f:
        winstate = f.readlines()
    winstate.reverse()

    sys.stdout.write('\n\n')

    index = 0
    orig_index = -1
    index_map = []
    remove_hwnd_list = []
    columns = console.get_buffer_size()[0] - 6
    currHwnd = py_GetConsoleWindow()

    for line in winstate:
        orig_index += 1
        states = line.split(winstate_separator)
        if len(states) != 3:
            print("Warning: unsupported line for windows switch: ", line)
            return

        hwnd  = int(states[0])
        if hwnd == currHwnd:
            continue
        if not py_IsWindow(hwnd):
            remove_hwnd_list.append(hwnd)
            continue

        curr_index_char = chr(ord('a') + index)
        index += 1
        index_map.append(orig_index)
        pwd = states[1].strip()
        cmd = states[2].strip()
        output_line = ''
        if len(pwd) + len(cmd) > columns:
            if len(pwd) > columns:
                output_line = pwd[0:columns-3] + '...'

        output_line = pwd + '> ' + cmd

        sys.stdout.write(curr_index_char + ': ' + output_line + '\n')

    sys.stdout.write('\n')
    message = ' Press a-z to switch to target PyCmd, space to ignore: '
    sys.stdout.write(message)

    rec = console.read_input()
    select_id = ord(rec.Char) - ord('a')
    #TODO: refresh current line instead of output new line?
    # Why 1 '\n' doesn't work? Know why, because cmd prompt is up for 1 line,
    # which occupies the message line scrolled by 1 line
    #sys.stdout.write('\n\n')
    sys.stdout.write('\r' + ' ' * len(message))
    if 0 <= select_id < index:
        to_line = winstate[index_map[select_id]]
        to_line_list = to_line.split(winstate_separator)
        to_hwnd = int(to_line_list[0])
        PyCmdUtils.SwitchToHwnd(to_hwnd)

        update_window_state(to_hwnd, to_line_list[1], to_line_list[2], remove_hwnd_list)

init()
