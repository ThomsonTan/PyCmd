import os, console, sys
import PyCmd, PyCmdUtils

windows_state_path = 'win_stat.txt'
winstate_separator = '^$^'
def update_window_state(hwnd, cmd = '', pwd = ''):
    winstate_full_path = os.path.join(PyCmd.pycmd_data_dir, windows_state_path)
    
    with open(winstate_full_path, 'r+') as f:
        winstate = f.readlines()
        f.seek(0)

        for line in winstate:
            if not line.startswith(str(hwnd)):
                f.write(line)
            else:
                stats = line.split(winstate_separator)
                if len(stats) != 3:
                    print("Warning: unsupported line for windows switch ", line)
                
                if len(cmd) == 0:
                    cmd = stats[1]
                else:
                    cmd = cmd.trim()
                if len(pwd) == 0:
                    pwd = stats[2]
                else:
                    pwd = pwd.trim()
        new_line = winstate_separator.join([str(hwnd), cmd, pwd])
        f.write(new_lien)
        f.truncate()

def list_and_switch():
    with open(winstate_full_path, 'r') as f:
        winstate = f.readlines().reverse()

    index = 0
    total_options = 0
    columns = console.get_buffer_size()[0] - 6
    for line in winstate:
        states = line.split(winstate.separate)
        if len(states) != 3:
            print("Warning: unsupported line for windows switch: ", line)
            return

        curr_index_char = chr(ord('a') + index)
        index += 1
        output_line = ''
        if len(states[1] + len(states[2])) > columns:
            if len(states[1]) > columns:
                output_line = states[0:columns-3] + '...'

        output_line = states[1] + ' : ' + states[2]

        print(curr_index_char, ': ', output_line)
        total_options += 1

    message = ' Press a-z to switch to target window, space to ignore: '
    sys.stdout.write(message)

    rec = console.read_input()
    select_id = ord(rec.Char) - ord('a')
    if 0 <= select_id < total_options:
        # select target window in winstate[select_id]
        PyCmdUtils.SwitchToHwnd(int(winstate[select_id][0]))

        update_window_state(hwnd)

