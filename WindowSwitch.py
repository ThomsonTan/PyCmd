import os, console, sys, ctypes
from common import expand_env_vars
import PyCmdUtils
from pycmd_public import color

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

    if not os.path.exists(pycmd_data_dir):
        os.mkdir(pycmd_data_dir)
    if not os.path.exists(winstate_full_path):
        open(winstate_full_path, 'a').close()

def update_window_state(pwd = '', cmd = '', hwnd = None, remove_hwnd_list=[]):
    """Update status for given hwnd"""
    
    if hwnd == None:
        hwnd = py_GetConsoleWindow()
    pwd = pwd.strip()
    cmd = cmd.strip()
    remove_hwnd = len(pwd) == 0 and len(cmd) == 0

    if not remove_hwnd and len(pwd) == 0:
        pwd = os.getcwd()

    with open(winstate_full_path, 'r+') as f:
        winstate = f.readlines()
        f.seek(0)

        for line in winstate:
            line = line.strip()
            stats = line.split(winstate_separator)
            if len(stats) != 3:
                continue
            if int(stats[0]) in remove_hwnd_list:
                # remove invalid line
                continue
            if not line.startswith(str(hwnd)):
                f.write(line + '\n')
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

    first_line = True
    index = 0
    orig_index = -1
    index_map = []
    remove_hwnd_list = []
    columns = console.get_buffer_size()[0] - 3
    currHwnd = py_GetConsoleWindow()

    for line in winstate:
        orig_index += 1
        states = line.split(winstate_separator)
        if len(states) != 3:
            print("Warning: unsupported line for windows switch: ", line)
            continue

        hwnd  = int(states[0])
        if hwnd == currHwnd:
            continue
        if not py_IsWindow(hwnd):
            remove_hwnd_list.append(hwnd)
            continue

        curr_index_char = chr(ord('a') + index)
        index += 1
        index_map.append(orig_index)
        pwd = states[1].strip() + '> '
        cmd = states[2].strip()

        if len(pwd) > columns:
            pwd = pwd[0: column - 5] + '...> '
            cmd = ''
        else:
            left_columns = columns - len(pwd)
            if len(cmd) > left_columns:
                if left_columns >= 3:
                    cmd = cmd[0:left_columns - 3] + '...'

        if first_line:
            sys.stdout.write('\n\n')
            first_line = False

        if index % 2 == 0:
            color_str_cmd = color.Fore.RED + color.Fore.CLEAR_BRIGHT
            color_str_pwd = color.Fore.RED + color.Fore.SET_BRIGHT
        else:
            color_str_cmd = color.Fore.GREEN + color.Fore.CLEAR_BRIGHT
            color_str_pwd = color.Fore.GREEN + color.Fore.SET_BRIGHT
        sys.stdout.write(color_str_pwd + curr_index_char + ': ' + pwd + color_str_cmd + cmd + '\n')

    if index == 0:
        return
    sys.stdout.write(color.Fore.DEFAULT + '\n')
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

        update_window_state(to_line_list[1], to_line_list[2], to_hwnd, remove_hwnd_list)

init()
