import sys, os, tempfile, signal, time, traceback, codecs

import code
import ctypes
import fileinput

from common import parse_line, unescape, sep_tokens, sep_chars
from common import expand_tilde, expand_env_vars
from common import associated_application, full_executable_path, is_gui_application
from completion import complete_file, complete_wildcard, complete_result_map, complete_env_var, find_common_prefix, has_wildcards, wildcard_to_regex
from InputState import ActionCode, InputState
from DirHistory import DirHistory
import console
from sys import stdout, stderr
from console import move_cursor, get_cursor, cursor_backward, set_cursor_visible
from console import read_input, write_input
from console import is_ctrl_pressed, is_alt_pressed, is_shift_pressed, is_control_only
from console import scroll_buffer, get_viewport
from console import remove_escape_sequences
from pycmd_public import color, appearance, behavior
from common import apply_settings, sanitize_settings

import command_cc

import string
import datetime

import PyCmdUtils
import WindowSwitch, pathlib

pycmd_data_dir = None
pycmd_install_dir = None
state = None
dir_hist = None
tmpfile = None
resultMapFilePath = None
create_result_map = True
cmdLineFilePath = None
max_cmd_history_lines = 10000

char2int = {'0':0, '1':1, '2':2, '3':3, '4':4, '5':5, '6':6, '7':7, '8':8, '9':9}

def init():
    # %APPDATA% is not always defined (e.g. when using runas.exe)
    if 'APPDATA' in os.environ.keys():
        APPDATA = '%APPDATA%'
    else:
        APPDATA = '%USERPROFILE%\\Application Data'
    global pycmd_data_dir
    pycmd_data_dir = expand_env_vars(APPDATA + '\\PyCmd')

    # Create app data directory structure if not present
    if not os.path.isdir(pycmd_data_dir):
        os.mkdir(pycmd_data_dir)
    if not os.path.isdir(pycmd_data_dir + '\\tmp'):
        os.mkdir(pycmd_data_dir + '\\tmp')

    # Determine the "installation" directory
    global pycmd_install_dir
    pycmd_install_dir = os.path.dirname(os.path.abspath(sys.argv[0]))

    # Current state of the input (prompt, entered chars, history)
    global state
    state = InputState()

    # Read/initialize command history
    state.history.list = read_history(pycmd_data_dir + '\\history')

    # Read/initialize directory history
    global dir_hist
    dir_hist = DirHistory()
    dir_hist.locations = read_history(pycmd_data_dir + '\\dir_history')
    dir_hist.index = len(dir_hist.locations) - 1
    dir_hist.visit_cwd()

    # Create temporary file
    global tmpfile
    (handle, tmpfile) = tempfile.mkstemp(dir = pycmd_data_dir + '\\tmp')
    os.close(handle)

    # Create result map file
    global resultMapFilePath
    if 'PYCMD_RESULT_MAP_FILE_PATH' in os.environ:
        resultMapFilePath = os.environ['PYCMD_RESULT_MAP_FILE_PATH']
        global create_result_map
        create_result_map = False
    else:
        (handle, resultMapFilePath) = tempfile.mkstemp(dir = pycmd_data_dir + '\\tmp')
        os.close(handle)
        os.environ['PYCMD_RESULT_MAP_FILE_PATH'] = resultMapFilePath

    # Create command line file
    global cmdLineFilePath
    (handle, cmdLineFilePath) = tempfile.mkstemp(dir = pycmd_data_dir + '\\tmp')
    os.close(handle)

    # Catch SIGINT to emulate Ctrl-C key combo
    signal.signal(signal.SIGINT, signal_handler)

def deinit():
    os.remove(tmpfile)
    os.remove(cmdLineFilePath)

    global create_result_map
    if create_result_map:
        os.remove(resultMapFilePath)

def main():
    title_prefix = ""

    console.set_console_mode(4 | console.get_console_mode())

    # Apply global and user configurations
    apply_settings(pycmd_install_dir + '\\init.py')
    apply_settings(pycmd_data_dir + '\\init.py')
    sanitize_settings()

    # Parse arguments
    arg = 1
    while arg < len(sys.argv):
        switch = sys.argv[arg].upper()
        rest = ['"' + t + '"' if os.path.exists(t) else t
                for t in sys.argv[arg+1:]]
        if switch in ['/K', '-K']:
            # Run the specified command and continue
            if rest != []:
                run_command(rest)
                dir_hist.visit_cwd()
                break
        elif switch in ['/C', '-C']:
            # Run the specified command end exit
            if rest != []:
                run_command(rest)
            internal_exit()
        elif switch in ['/H', '/?', '-H']:
            # Show usage information and exit
            print_usage()
            internal_exit()
        elif switch in ['/T', '-T']:
            if arg == len(sys.argv) - 1:
                stderr.write('PyCmd: no title specified to \'-t\'\n')
                print_usage()
                internal_exit()
            title_prefix = sys.argv[arg + 1] + ' - '
            arg += 1
        elif switch in ['/I', '-I']:
            if arg == len(sys.argv) - 1:
                stderr.write('PyCmd: no script specified to \'-i\'\n')
                print_usage()
                internal_exit()
            apply_settings(sys.argv[arg + 1])
            sanitize_settings()
            arg += 1
        elif switch in ['/Q', '-Q']:
            # Quiet mode: suppress messages
            behavior.quiet_mode = True
        elif switch in ['/B', '-B']:
            # Build mode, set the build dir
            # Don't override it if already set here.
            if not 'PYCMD_BUILD_DIR' in os.environ:
                command_cc.set_build_dir_env_var()
        else:
            # Invalid command line switch
            stderr.write('PyCmd: unrecognized option `' + sys.argv[arg] + '\'\n')
            print_usage()
            internal_exit()
        arg += 1

    if title_prefix == "" :
        title_prefix = console.get_console_title()
        # TODO: fix python.exe path exposed in Python3

    if not behavior.quiet_mode:
        # Print some splash text
        #try:
        #    #from buildinfo import build_info
        #except (ImportError, ie):
        #    build_info = '<no build info>'
        build_info = '<no build info>'


        print()
        print('Welcome to PyCmd %s!' % build_info)
        print()

    # Run an empty command to initialize environment
    run_command(['echo', '>', 'NUL'])

    no_new_prompt = False
    no_history_update = False

    edit_cmd_line = False
    interactiveCon = None

    # Main loop
    while True:
        # Prepare buffer for reading one line
        if no_new_prompt:
            # ensure old input are erased
            state.before_cursor = ''
            state.after_cursor = ''
        else:
            state.reset_line(appearance.prompt())
        scrolling = False
        auto_select = False
        force_repaint = True
        dir_hist.shown = False
        debug_run = False
        no_history_update = False
        if no_new_prompt == False:
            stdout.write('\n')
        else:
            no_new_prompt = False

        while True:
            # Update console title and environment
            curdir = os.getcwd()
            curdir = curdir[0].upper() + curdir[1:]
            # console.set_console_title(title_prefix + curdir + ' - PyCmd')
            console.set_console_title(title_prefix + b' - PyCmd')
            os.environ['CD'] = curdir

            if state.changed() or force_repaint:
                prev_total_len = len(remove_escape_sequences(state.prev_prompt) + state.prev_before_cursor + state.prev_after_cursor)
                set_cursor_visible(False)
                # a regression in Windows 10? Haven't observed this before.
                # When input reaches the right scroll bar of cmd.exe window, the cursor doesn't move to the next position (next line),
                # instead it remains on the last input character. Before the fix, cursor_backward moves back one more char in this 
                # case then move to upper line, then output from previous line and leave garbages in the current line
                backwardlen = len(remove_escape_sequences(state.prev_prompt) + state.prev_before_cursor)
                # backwardlen should > 0
                # if backwardlen % console.get_buffer_size()[0] == 0 :
                # when there are multiple lines, delete the current line to the begining then delete one more,
                # cursor will move up to one line above, but the cursor position is the column before the last one (one the last char,
                # not after it). len - 1 should always be safe
                backwardlen = backwardlen - 1
                cursor_backward(backwardlen)
                stdout.write('\r')

                # Update the offset of the directory history in case of overflow
                # Note that if the history display is marked as 'dirty'
                # (dir_hist.shown == False) the result of this action can be
                # ignored
                dir_hist.check_overflow(remove_escape_sequences(state.prompt))
                
                path_levels = state.prompt.count('\\') + 1
                if path_levels == 2 and state.prompt[1] == ':' and state.prompt[2] == '\\' \
                    and state.prompt[3] == '>' :
                    path_levels = path_levels - 1
                 
                dot_count = 0
                
                # seems doesn't count . at current cursor position is the best
                #if len(state.after_cursor) > 0 and state.after_cursor[0] == '.' :
                #    dot_count = 1

                i = 0
                for i in range(len(state.before_cursor) - 1, -1, -1) :
                    if state.before_cursor[i] == '.' :
                        dot_count = dot_count + 1
                    else :
                        break;

                if len(state.before_cursor) == 0 or \
                        (state.before_cursor[i] != ' ' and state.before_cursor[i] != '.') :
                    dot_count = 0
                # Write current line
                if dot_count > 1 and dot_count <= path_levels :
                    path_level_from_root = path_levels - dot_count
                    #print '\n', path_levels, path_level_from_root, dot_count, '\n'
                    before_hint_folder_index = 0
                    i_path = 0
                    i_id = 0
                    while i_path < path_level_from_root :
                        if state.prompt[i_id] != '\\' and state.prompt[i_id] != '>':
                            i_id = i_id + 1
                            continue
                        else :
                            i_id = i_id + 1
                            i_path = i_path + 1
                    
                    hint_folder_before = state.prompt[:i_id]
                    i_endid = i_id
                    while True :
                        if state.prompt[i_endid] != '\\' and state.prompt[i_endid] != '>':
                            i_endid = i_endid + 1
                        else :
                            break;
                    hint_folder = state.prompt[i_id:i_endid]
                    hint_folder_after = state.prompt[i_endid:]
                    stdout.write(u'\r' + color.Fore.DEFAULT + color.Back.DEFAULT + appearance.colors.prompt +
                              hint_folder_before)

                    stdout.write(color.Fore.DEFAULT + color.Back.DEFAULT + appearance.colors.search_filter +
                              hint_folder)

                    stdout.write(color.Fore.DEFAULT + color.Back.DEFAULT + appearance.colors.prompt +
                              hint_folder_after +
                              color.Fore.DEFAULT + color.Back.DEFAULT + appearance.colors.text)
                else :
                    # Output command prompt prefix
                    stdout.write(u'\r' + color.Fore.DEFAULT + color.Back.DEFAULT + appearance.colors.prompt +
                              state.prompt +
                              color.Fore.DEFAULT + color.Back.DEFAULT + appearance.colors.text)
                line = state.before_cursor + state.after_cursor
                if state.history.filter == '':
                    sel_start, sel_end = state.get_selection_range()
                    stdout.write('' + line[:sel_start] +'' +
                                 appearance.colors.selection +
                                 line[sel_start: sel_end] +
                                 color.Fore.DEFAULT + color.Back.DEFAULT + appearance.colors.text +
                                 line[sel_end:])
                else:
                    pos = 0
                    colored_line = ''
                    for (start, end) in state.history.current()[1]:
                        colored_line += color.Fore.DEFAULT + color.Back.DEFAULT + appearance.colors.text + line[pos : start]
                        colored_line += appearance.colors.search_filter + line[start : end]
                        pos = end
                    colored_line += color.Fore.DEFAULT + color.Back.DEFAULT + appearance.colors.text + line[pos:]
                    stdout.write(colored_line)

                # Erase remaining chars from old line
                to_erase = prev_total_len - len(remove_escape_sequences(state.prompt) + state.before_cursor + state.after_cursor)
                if to_erase > 0:
                    stdout.write(color.Fore.DEFAULT + color.Back.DEFAULT + ' ' * to_erase)
                    cursor_backward(to_erase)

                # Move cursor to the correct position
                set_cursor_visible(True)
                cursor_backward(len(state.after_cursor))

            # Prepare new input state
            state.step_line()

            # Read and process a keyboard event
            rec = read_input()
            select = auto_select or is_shift_pressed(rec)

            # Will be overriden if Shift-PgUp/Dn is pressed
            force_repaint = not is_control_only(rec)    

            #print '\n\n', rec.keyDown, rec.char, rec.virtualKeyCode, rec.controlKeyState, '\n\n'
            if is_ctrl_pressed(rec) and not is_alt_pressed(rec):  # Ctrl-Something
                if rec.Char == chr(4):                  # Ctrl-D
                    if state.before_cursor + state.after_cursor == '':
                        internal_exit('\r\nBye!')
                    else:
                        state.handle(ActionCode.ACTION_DELETE)
                elif rec.Char == chr(31):                   # Ctrl-_
                    state.handle(ActionCode.ACTION_UNDO_EMACS)
                    auto_select = False
                elif rec.VirtualKeyCode == 75:          # Ctrl-K
                    state.handle(ActionCode.ACTION_KILL_EOL)
                elif rec.VirtualKeyCode == 32:          # Ctrl-Space
                    auto_select = True
                    state.reset_selection()
                elif rec.VirtualKeyCode == 83:          # Ctrl-S to run under debugger
                    debug_run = True
                    state.history.reset()
                    break
                elif rec.VirtualKeyCode == 71:          # Ctrl-G
                    state.history.reset()
                    break
                    # if scrolling:
                    #     scrolling = False
                    # else:
                    #     state.handle(ActionCode.ACTION_ESCAPE)
                    #     save_history(state.history.list,
                    #                  pycmd_data_dir + '\\history',
                    #                  max_cmd_history_lines)
                    #     auto_select = False
                elif rec.VirtualKeyCode == 65:          # Ctrl-A, no easy typing remap to Alt-A
                    state.handle(ActionCode.ACTION_HOME, select)
                elif rec.VirtualKeyCode == 69:          # Ctrl-E
                    state.handle(ActionCode.ACTION_END, select)
                elif rec.VirtualKeyCode == 66:          # Ctrl-B
                    state.handle(ActionCode.ACTION_LEFT_WORD, select)
                elif rec.VirtualKeyCode == 70:          # Ctrl-F
                    state.handle(ActionCode.ACTION_RIGHT_WORD, select)
                elif rec.VirtualKeyCode == 72:          # Ctrl-H
                    state.handle(ActionCode.ACTION_LEFT, select)
                # Ctrl-J and Ctrl-K are unavailable for remapping in cmd.exe?
                elif rec.VirtualKeyCode == 76:          # Ctrl-L
                    state.handle(ActionCode.ACTION_RIGHT, select)
                # elif rec.VirtualKeyCode == 80:          # Ctrl-P
                #     state.handle(ActionCode.ACTION_PREV)
                # elif rec.VirtualKeyCode == 78:          # Ctrl-N
                #     state.handle(ActionCode.ACTION_NEXT)
                # elif rec.VirtualKeyCode == 37:          # Ctrl-Left
                #     state.handle(ActionCode.ACTION_LEFT_WORD, select)
                # elif rec.VirtualKeyCode == 39:          # Ctrl-Right
                #     state.handle(ActionCode.ACTION_RIGHT_WORD, select)
                # elif rec.VirtualKeyCode == 46:          # Ctrl-Delete
                #     state.handle(ActionCode.ACTION_DELETE_WORD)
                elif rec.VirtualKeyCode == 67:          # Ctrl-C
                    # The Ctrl-C signal is caught by our custom handler, and a
                    # synthetic keyboard event is created so that we can catch
                    # it here
                    if state.get_selection() != '':
                        state.handle(ActionCode.ACTION_COPY)
                    else:
                        state.handle(ActionCode.ACTION_ESCAPE)
                    auto_select = False
                elif rec.VirtualKeyCode == 82:          # Ctrl-R
                    state.handle(ActionCode.ACTION_LEFT_WORD, select, sep_chars)
                elif rec.VirtualKeyCode == 84:          # Ctrl-T
                    state.handle(ActionCode.ACTION_RIGHT_WORD, select, sep_chars)
                elif rec.VirtualKeyCode == 88:          # Ctrl-X
                    state.handle(ActionCode.ACTION_CUT)
                    auto_select = False
                # elif rec.VirtualKeyCode == 87:          # Ctrl-W
                #     state.handle(ActionCode.ACTION_CUT)
                #     auto_select = False
                elif rec.VirtualKeyCode == 87:          # Ctrl-W
                    state.handle(ActionCode.ACTION_BACKSPACE_WORD, sep_chars)
                #elif rec.VirtualKeyCode == 86:          # Ctrl-V
                #    state.handle(ActionCode.ACTION_PASTE)
                #    auto_select = False
                # elif rec.VirtualKeyCode == 89:          # Ctrl-Y
                #     state.handle(ActionCode.ACTION_PASTE)
                #     auto_select = False
                # elif rec.VirtualKeyCode == 8:           # Ctrl-Backspace
                #     state.handle(ActionCode.ACTION_BACKSPACE_WORD)
                elif rec.VirtualKeyCode == 90:  
                    if not is_shift_pressed(rec):       # Ctrl-Z
                        state.handle(ActionCode.ACTION_UNDO)
                    else:                               # Ctrl-Shift-Z
                        state.handle(ActionCode.ACTION_REDO)
                    auto_select = False
            elif is_alt_pressed(rec) and not is_ctrl_pressed(rec):      # Alt-Something
                if rec.VirtualKeyCode in [37, 39, 72, 76] + list(range(49, 59)): # Dir history 
                    if state.before_cursor + state.after_cursor == '':
                        state.reset_prev_line()
                        if rec.VirtualKeyCode == 37 or rec.VirtualKeyCode == 72: # Alt-Left or Alt-H
                            changed = dir_hist.go_left()
                        elif rec.VirtualKeyCode == 39 or rec.VirtualKeyCode == 76: # Alt-Right or Alt-L
                            changed = dir_hist.go_right()
                        else:                                   # Alt-1..Alt-9        
                            changed = dir_hist.jump(rec.VirtualKeyCode - 48)
                        if changed:
                            state.prev_prompt = state.prompt
                            state.prompt = appearance.prompt()
                        save_history(dir_hist.locations,
                                     pycmd_data_dir + '\\dir_history',
                                     dir_hist.max_len)
                        if dir_hist.shown:
                            dir_hist.display()
                            stdout.write(state.prev_prompt)
                    else:
                        if rec.VirtualKeyCode == 37:            # Alt-Left
                            state.handle(ActionCode.ACTION_LEFT_WORD, select)
                        elif rec.VirtualKeyCode == 39:          # Alt-Right
                            state.handle(ActionCode.ACTION_RIGHT_WORD, select)
                elif rec.VirtualKeyCode == 65:          # Alt-A
                    state.handle(ActionCode.ACTION_HOME)
                elif rec.VirtualKeyCode == 66:          # Alt-B
                    state.handle(ActionCode.ACTION_BACKSPACE_WORD)
                elif rec.VirtualKeyCode == 67:          # Alt-C
                    force_repaint = False
                    state.handle(ActionCode.ACTION_SWITCH_TO_GVIM)
                elif rec.VirtualKeyCode == 69:          # Alt-E
                    force_repaint = False
                    state.handle(ActionCode.ACTION_OPEN_CLIPBOARD)
                elif rec.VirtualKeyCode == 70:          # Alt-F
                    state.handle(ActionCode.ACTION_DELETE_WORD)
                elif rec.VirtualKeyCode == 71:          # Alt-G
                    edit_cmd_line = True
                    state.history.reset()
                    break
                # elif rec.VirtualKeyCode == 80:          # Alt-P
                #     state.handle(ActionCode.ACTION_PREV)
                # elif rec.VirtualKeyCode == 78:          # Alt-N
                #     state.handle(ActionCode.ACTION_NEXT)
                elif rec.VirtualKeyCode == 68:          # Alt-D
                    if state.before_cursor + state.after_cursor == '':
                        dir_hist.display()
                        dir_hist.check_overflow(remove_escape_sequences(state.prev_prompt))
                        stdout.write(state.prev_prompt)
                    else:
                        state.handle(ActionCode.ACTION_DELETE_WORD) 
                elif rec.VirtualKeyCode == 82:          # Alt-R
                    state.handle(ActionCode.ACTION_BACKSPACE_WORD, sep_chars)
                elif rec.VirtualKeyCode == 83:           # Alt-S
                    WindowSwitch.list_and_switch()
                elif rec.VirtualKeyCode == 84:          # Alt-T
                    state.handle(ActionCode.ACTION_DELETE_WORD, sep_chars)
                elif rec.VirtualKeyCode == 85:          # Alt-U
                    if not is_shift_pressed(rec):
                        state.handle(ActionCode.ACTION_UNDO)
                    else:
                        state.handle(ActionCode.ACTION_REDO) #Alt-Shift-U
                elif rec.VirtualKeyCode == 86:          # Alt-V
                    state.handle(ActionCode.ACTION_PASTE)
                    auto_select = False
                elif rec.VirtualKeyCode == 87:          # Alt-W
                    state.handle(ActionCode.ACTION_COPY)
                    state.reset_selection()
                    auto_select = False
                elif rec.VirtualKeyCode == 46:          # Alt-Delete
                    state.handle(ActionCode.ACTION_DELETE_WORD)
                elif rec.VirtualKeyCode == 8:           # Alt-Backspace
                    state.handle(ActionCode.ACTION_BACKSPACE_WORD)
                elif rec.VirtualKeyCode == 191:         # Alt-/
                    state.handle(ActionCode.ACTION_EXPAND)
                elif rec.VirtualKeyCode == 75 or rec.VirtualKeyCode == 88:  # Alt-K or Alt-X
                    state.handle(ActionCode.ACTION_PREV)
                elif rec.VirtualKeyCode == 74:  # Alt-J
                    state.handle(ActionCode.ACTION_NEXT)
            elif is_shift_pressed(rec) and rec.VirtualKeyCode == 33:    # Shift-PgUp
                (_, t, _, b) = get_viewport()
                scroll_buffer(t - b + 2)
                scrolling = True
                force_repaint = False
            elif is_shift_pressed(rec) and rec.VirtualKeyCode == 34:    # Shift-PgDn
                (_, t, _, b) = get_viewport()
                scroll_buffer(b - t - 2)
                scrolling = True
                force_repaint = False
            else:                                       # Clean key (no modifiers)
                if rec.Char == chr(0):                  # Special key (arrows and such)
                    if rec.VirtualKeyCode == 37 or rec.VirtualKeyCode == 39:
                        if state.before_cursor + state.after_cursor == '':
                            state.reset_prev_line()
                            if rec.VirtualKeyCode == 37 : # Left
                                changed = dir_hist.go_left()
                            elif rec.VirtualKeyCode == 39 : # Right
                                changed = dir_hist.go_right()
                            if changed:
                                state.prev_prompt = state.prompt
                                state.prompt = appearance.prompt()
                            save_history(dir_hist.locations,
                                         pycmd_data_dir + '\\dir_history',
                                         dir_hist.max_len)
                            if dir_hist.shown:
                                dir_hist.display()
                                stdout.write(state.prev_prompt)
                        elif rec.VirtualKeyCode == 37:        # Left arrow
                            state.handle(ActionCode.ACTION_LEFT, select)
                        elif rec.VirtualKeyCode == 39:      # Right arrow
                            state.handle(ActionCode.ACTION_RIGHT, select)
                    elif rec.VirtualKeyCode == 36:      # Home
                        state.handle(ActionCode.ACTION_HOME, select)
                    elif rec.VirtualKeyCode == 35:      # End
                        state.handle(ActionCode.ACTION_END, select)
                    elif rec.VirtualKeyCode == 38:      # Up arrow
                        state.handle(ActionCode.ACTION_PREV)
                    elif rec.VirtualKeyCode == 40:      # Down arrow
                        state.handle(ActionCode.ACTION_NEXT)
                    elif rec.VirtualKeyCode == 46:      # Delete
                        state.handle(ActionCode.ACTION_DELETE)
                elif rec.Char == chr(13):               # Enter
                    state.history.reset()
                    break
                elif rec.Char == chr(27):               # Esc
                    if scrolling:
                        scrolling = False
                    else:
                        state.handle(ActionCode.ACTION_ESCAPE)
                        save_history(state.history.list,
                                     pycmd_data_dir + '\\history',
                                     max_cmd_history_lines)
                        auto_select = False
                elif rec.Char == '\t':                  # Tab
                    stdout.write(state.after_cursor)        # Move cursor to the end

                    tokens = parse_line(state.before_cursor)
                    if tokens == [] or state.before_cursor[-1] in sep_chars:
                        tokens.append('')   # This saves some checks later on
                    
                    # Check ... expansion at first
                    last_token_len = len(tokens[-1])
                    if last_token_len >= 2 and \
                            (tokens[-1].count('.') == last_token_len) :
                        suggestions = []
                        expanded_token = '..\\'
                        for i in range(last_token_len - 2) :
                            expanded_token = expanded_token + '..\\'
                        
                        tokens[-1] = expanded_token
                        completed = ' '.join(tokens)
                    # handle expand of @a
                    elif last_token_len == 2 and tokens[-1][0] == '@':
                        suggestions = []
                        completed = ' '
                        complete_index = ord(tokens[-1][1])
                        if complete_index >= ord('a') and complete_index <= ord('z'):
                            complete_index = complete_index - ord('a')
                            completed = complete_result_map(complete_index, resultMapFilePath)
                            if len(completed) > 0:
                                tokens[-1] = completed
                            completed = ' '.join(tokens)
                        elif complete_index == ord('@'):
                            cmdLineFromFile = open(cmdLineFilePath)
                            cmdLineFromFileStrip = cmdLineFromFile.read().strip();
                            cmdLineFromFile.close()
                            if len(cmdLineFromFileStrip) > 0:
                                tokens[-1] = cmdLineFromFileStrip
                                completed = cmdLineFromFileStrip

                    # handle expand of $a which is the last arg
                    elif last_token_len == 2 and tokens[-1][0] == '$':
                        suggestions = []
                        completed = ' '
                        expand_char = tokens[-1][1]

                        if expand_char == 'a' and 'ALT_DRIVE' in os.environ and len(os.environ['ALT_DRIVE']) == 1:
                            # switch to alternate drive with the same path as current dir
                            alt_drive = os.environ['ALT_DRIVE']
                            curr_dir = os.getcwd()
                            if curr_dir[0] != alt_drive:
                                tokens[-1] = alt_drive + curr_dir[1:] + '\\'
                                completed = ' '.join(tokens)
                        elif expand_char == 'o' and 'SDXROOT' in os.environ:
                            sdx_root = os.environ['SDXROOT'].lower() + '\\'
                            obj_root = os.environ['OBJECT_ROOT'].lower()
                            o_path = os.environ['O']
                            curr_dir = os.getcwd().lower()
                            if curr_dir.startswith(sdx_root):
                                rel_path = curr_dir[len(sdx_root):]
                                if os.path.isfile('sources'):
                                    tokens[-1] = os.path.join(obj_root, rel_path, o_path) + '\\'
                                else:
                                    tokens[-1] = os.path.join(obj_root, rel_path) + '\\'
                                completed = ' '.join(tokens)
                    elif last_token_len == 1 and tokens[-1] == '@' and tokens[0] == 'cmake':
                        # only one of below 2 are used?
                        suggestions = []
                        tokens[-1] = command_cc.complete_suggestion_for_cc()
                        completed = ' '.join(tokens)
                    elif tokens[0] == 'cc':
                        suggestions = []
                        cc_expand_to_dir = command_cc.expand_path(-1)
                        if cc_expand_to_dir[-1] != '\\' and os.path.isdir(cc_expand_to_dir):
                            cc_expand_to_dir += '\\'
                        tokens[0] = cc_expand_to_dir
                        completed = tokens[0]

                    # handle expansion of ctest -R testname to case insensitive comparison.
                    # no need to handle expanding regex which contains `[' or ']` already.
                    elif len(tokens) > 2 and tokens[0] == 'ctest' and tokens[-2] == '-R':
                        suggestions = []
                        ctest_regex_ignore_case = ''
                        for ch in tokens[-1]:
                            if ch.isalpha():
                                ctest_regex_ignore_case += '[' + ch.swapcase() + ch + ']'
                            else:
                                ctest_regex_ignore_case += ch
                        tokens[-1] = ctest_regex_ignore_case
                        completed = ' '.join(tokens)

                    elif tokens[-1].strip('"').count('%') % 2 == 1:
                        (completed, suggestions) = complete_env_var(state.before_cursor)
                    elif has_wildcards(tokens[-1]):
                        (completed, suggestions)  = complete_wildcard(state.before_cursor)
                    else:
                        (completed, suggestions)  = complete_file(state.before_cursor)

                    # Show multiple completions if available
                    if len(suggestions) > 1:
                        dir_hist.shown = False  # The displayed dirhist is no longer valid
                        column_width = max([len(s) for s in suggestions]) + 10
                        if column_width > console.get_buffer_size()[0] - 1:
                            column_width = console.get_buffer_size()[0] - 1
                        if len(suggestions) > (get_viewport()[3] - get_viewport()[1]) / 4:
                            # We print multiple columns to save space
                            num_columns = (console.get_buffer_size()[0] - 1) // column_width
                        else:
                            # We print a single column for clarity
                            num_columns = 1
                        num_lines = len(suggestions) / num_columns
                        if len(suggestions) % num_columns != 0:
                            num_lines += 1

                        num_screens = 1.0 * num_lines / (get_viewport()[3] - get_viewport()[1])
                        if num_screens >= 0.9:
                            # We ask for confirmation before displaying many completions
                            (c_x, c_y) = get_cursor()
                            offset_from_bottom = console.get_buffer_size()[1] - c_y
                            message = ' Scroll ' + str(int(round(num_screens))) + ' screens? [Tab] '
                            stdout.write('\n' + message)
                            rec = read_input()
                            move_cursor(c_x, console.get_buffer_size()[1] - offset_from_bottom)
                            stdout.write('\n' + ' ' * len(message))
                            move_cursor(c_x, console.get_buffer_size()[1] - offset_from_bottom)
                            if rec.Char != '\t':
                                continue
                            
                        stdout.write('\n')
                        num_col_could_choose = num_lines # num_lines > 0
                        num_item_could_choose = len(string.ascii_lowercase)
                        while num_col_could_choose < num_item_could_choose :
                            num_col_could_choose = num_col_could_choose + num_lines
                        
                        num_col_could_choose = (num_col_could_choose + num_lines - 1) / num_lines
                            
                        
                        for line in range(0, int(num_lines)):
                            # Print one line
                            stdout.write('\r')
                            for column in range(0, num_columns):
                                if line + column * num_lines < len(suggestions):
                                    suggestion_id = int(line + column * num_lines)
                                    s = suggestions[suggestion_id]
                                    
                                    suggestion_prefix = ''
                                    if suggestion_id < num_item_could_choose :
                                        suggestion_prefix = string.ascii_lowercase[suggestion_id]+': '
                                    elif column < num_col_could_choose :
                                        suggestion_prefix = '   '
                                    else :
                                        suggestion_prefix = ''
                                    
                                    stdout.write(color.Fore.DEFAULT + color.Back.DEFAULT + suggestion_prefix)
                                    
                                    if has_wildcards(tokens[-1]):
                                        # Print wildcard matches in a different color
                                        tokens = parse_line(completed.rstrip('\\'))
                                        token = tokens[-1].replace('"', '')
                                        (_, _, prefix) = token.rpartition('\\')
                                        match = wildcard_to_regex(prefix + '*').match(s)
                                        current_index = 0
                                        for i in range(1, match.lastindex + 1):
                                            stdout.write(color.Fore.DEFAULT + color.Back.DEFAULT +
                                                         appearance.colors.completion_match +
                                                         s[current_index : match.start(i)] +
                                                         color.Fore.DEFAULT + color.Back.DEFAULT +
                                                         s[match.start(i) : match.end(i)])
                                            current_index = match.end(i)
                                        stdout.write(color.Fore.DEFAULT + color.Back.DEFAULT + ' ' * (column_width - len(s)))
                                    else:
                                        # Print the common part in a different color
                                        common_prefix_len = len(find_common_prefix(state.before_cursor, suggestions))
                                        stdout.write(color.Fore.DEFAULT + color.Back.DEFAULT +
                                                     appearance.colors.completion_match +
                                                     s[:common_prefix_len] +
                                                     color.Fore.DEFAULT + color.Back.DEFAULT +
                                                     s[common_prefix_len : ])
                                        stdout.write(color.Fore.DEFAULT + color.Back.DEFAULT + ' ' * (column_width - len(s)))
                                    
                            stdout.write('\n')
                        
                        # The below code looks a little tricky since it needs to preserve the position of existing result (no flickering)
                        stdout.write('\n')
                        (c_x, c_y) = get_cursor()
                        offset_from_bottom = console.get_buffer_size()[1] - c_y
                        message = ' Press a-z for completion, space to ignore: '
                        stdout.write(message)
                        rec = read_input()
                        move_cursor(c_x, console.get_buffer_size()[1] - offset_from_bottom)
                        stdout.write(' ' * len(message))
                        move_cursor(c_x, console.get_buffer_size()[1] - offset_from_bottom)                        
                        #stdout.write('\n ')
                        if rec.Char.isalpha() and string.ascii_lowercase.index(rec.Char) < len(suggestions):
                            # Don't append a space to end since it could be a foder end with '\',
                            # and completion could continue
                            suggest_item = suggestions[string.ascii_lowercase.index(rec.Char)]
                            
                            # if suggest_item has space inside
                            if suggest_item.find(' ') != -1 and tokens[-1][0] != '"':
                                tokens[-1] = '"' + tokens[-1]
                            
                            # append " if starts with it
                            if len(tokens[-1]) > 0 and tokens[-1][0] == '"' :
                                suggest_item = suggest_item + '"'
                            if len (tokens[-1]) > 0 and tokens[-1][-1] == '\\' :
                                # Complete for path, don't remove the previous one
                                tokens[-1] = tokens[-1] + suggest_item
                            else:
                                # handle partial completion
                                tokens[-1] = tokens[-1][:tokens[-1].rfind('\\') + 1] + suggest_item
                                # append space at the end if not a path completion
                                # if tokens[-1][0] is ", no need to add space to separete since 
                                # " will be appended anyway.
                                if not (suggest_item.endswith('\\') or suggest_item.endswith('\\"')):
                                    tokens[-1] = tokens[-1] + ' '

                            completed = ' '.join(tokens)
                        state.reset_prev_line()

                    state.handle(ActionCode.ACTION_COMPLETE, completed)
                elif rec.Char == chr(8):                # Backspace
                    state.handle(ActionCode.ACTION_BACKSPACE)
                else:                                   # Regular character
                    state.handle(ActionCode.ACTION_INSERT, rec.Char)

        # Done reading line, now execute
        stdout.write(state.after_cursor)        # Move cursor to the end
        stdout.write(color.Fore.DEFAULT + color.Back.DEFAULT)
        line = (state.before_cursor + state.after_cursor).strip()
        tokens = parse_line(line)
        if len(state.open_app) > 0 and edit_cmd_line:
            cmdLineFilePathWithLine = cmdLineFilePath
            # Why it writes \n on Windows by default, 'w'?, replace str doesn't work
            cmdFile = open(cmdLineFilePath, 'wb')
            # if no content in command line, write clipboard text to the temporary file
            if tokens == [] or tokens[0] == '':
                write_str = PyCmdUtils.GetClipboardText()
                if len(write_str) == 0:
                    continue
                cmdLineFilePathWithLine += '?$' # nav to the last line
            else:
                write_str = ' '.join(tokens).encode('utf-8')
            cmdFile.write(write_str)
            cmdFile.close()
            os.system(state.open_app + ' ' + cmdLineFilePathWithLine)
            edit_cmd_line = False
            no_new_prompt = True
        elif tokens == [] or tokens[0] == '':
            continue
        elif len(tokens) == 1 and tokens[0] == u'i':
            print("")
            try:
                color_label = 'Linux'
                import IPython
                from IPython.utils import PyColorize, coloransi
                from IPython.utils.coloransi import TermColors
                import token as imported_token
                # the default color LightBlue is not visible in cmd
                # see the ColorScheme definition in IPython/utils/PyColorize.py
                PyColorize.ANSICodeColors[color_label].colors[imported_token.STRING] = TermColors.DarkGray

                from traitlets.config import get_config
                c = get_config()
                c.InteractiveShellEmbed.colors = color_label
                c.InteractiveShellEmbed.confirm_exit = False
                # Why below commented code doesn't work?
                #IPython = __import__('IPython')
                #traitles = __import__('traitlets')
                #IPythonConfig = traitles.config.get_config()
                #IPythonConfig.InteractiveShellEmbed.color = "Linux"
                IPython.embed(banner1='', config=c)
            except Exception as ex:
                print("Missing IPython: ", str(ex))
            #run_command([u'c:\\python27\\python.exe', u'-c', u'"import IPython;IPython.embed(banner1=\'\')"'])
            continue
        elif tokens[0] == u'cg': # Connect to GVim window
            PyCmdUtils.ConnectWithGVim()
        # shortcut for change devlopment directory
        elif tokens[0] == u'cc':
            command_cc.run(tokens[1:])
        else:
            replace_python_cmd = False
            # no new line for gvim and code
            if tokens[0] == u'gv' or tokens[0] == u'c':
                no_new_prompt = True
                # TODO: normal path likely file path.
                if len(tokens) > 1:
                    # TODO: refactor the if statement
                    if len(tokens[1]) == 2 and tokens[1][0] == '@' and ord(tokens[1][1]) >= ord('a')  and ord(tokens[1][1]) <= ord('z') :
                        complete_index = ord(tokens[1][1]) - ord('a')
                        completed = complete_result_map(complete_index, resultMapFilePath)
                        if len(completed) > 0:
                            tokens[1] = completed
                    else:
                        for tok_id in range(1, len(tokens)):
                            curr_tok = tokens[tok_id]

                            if tokens[0] == u'gv' and curr_tok == '.':
                                curr_tok = os.getcwd()
                                tokens[tok_id] = curr_tok

                            if '\\\\' in curr_tok:
                                tokens[tok_id] = curr_tok.replace('\\\\', '\\')
                            # the path is absolute path like c:/tmp/t.py, gv expects c:\tmp/t.py
                            elif len(curr_tok) > 3 and curr_tok[1] == ':' and curr_tok[2] == '/':
                                tail_tok = curr_tok[3:]
                                last_delim = tail_tok.rfind(':')
                                if last_delim > 0 and tail_tok[last_delim+1:].isnumeric():
                                    tail_tok = tail_tok[:last_delim] + '?' + tail_tok[last_delim+1:]
                                tokens[tok_id] = curr_tok[:2] + '\\' + tail_tok

                            # to open folder, seems appending a dot to the path is more reliable for gvim
                            if tokens[0] == u'gv':
                                curr_tok = tokens[tok_id]
                                if os.path.isdir(curr_tok):
                                    if curr_tok[-1] != '.':
                                        if curr_tok[-1] == '/':
                                            curr_tok += '.'
                                        else:
                                            curr_tok += '/.'

                                        tokens[tok_id] = curr_tok

            elif tokens[0] == u'a':
                no_history_update = True

            # elif len(tokens) == 1 and tokens[0] in [u'n', u'e', u'l']:
            #     global n, e, l
            #     cmd_func = {u'n':n, u'e':e, u'l':l}
            #     if tokens[0] == u'l':
            #         # evaluate script after new line
            #         stdout.write('\n')
            #     try:
            #         cmd_func[tokens[0]]()
            #     except Exception as ex:
            #         print("Got exception: " + str(ex))
            #     continue
            elif tokens[0] in [u'p', u'pip'] :
                if tokens[0] == u'pip':
                    tokens.insert(0, u'-m')
                    tokens.insert(0, None)
                replace_python_cmd = True
            elif tokens[0].endswith('.py') or tokens[0].endswith('.py"'):
                tokens.insert(0, None)
                replace_python_cmd = True
            elif tokens[0] == 'time':
                tokens[0] = 'cmake -E time'
            if replace_python_cmd:
                if 'VIRTUAL_ENV' in os.environ:
                    tokens[0] = os.path.join(os.environ['VIRTUAL_ENV'], 'Scripts', 'python')
                elif u' ' in sys.executable:
                    tokens[0] = '"' + sys.executable + '"'
                else:
                    tokens[0] = sys.executable

            if no_new_prompt == False:
                stdout.write('\n')
            if tokens[0] == u's':
                tokens[0] = u'start'
                if len(tokens) == 2:
                    cmd_arg1 = tokens[1].replace('/', '\\')
                    # assumes it is dir
                    if os.path.isfile(os.path.expandvars(cmd_arg1)):
                        tokens[0] = u'explorer.exe'
                        cmd_arg1 = f'/select,"{cmd_arg1}"'
                    tokens[1] = cmd_arg1
            elif tokens[0] == u'which':
                tokens[0] = u'where'
            elif tokens[0] == u'cd' or tokens[0] == u'cdd':
                if len(tokens) == 2:
                    cmd_arg1 = tokens[1].replace('/', '\\')
                    if os.path.isfile(os.path.expandvars(cmd_arg1)):
                        cmd_arg1 = os.path.dirname(cmd_arg1)
                        if cmd_arg1 == '':
                            cmd_arg1 = '.'
                    tokens[1] = cmd_arg1
                    if tokens[0] == u'cdd':
                        # show the stack before CD
                        for dir_rec in dir_hist.get_dir_stack():
                            print(f'  {dir_rec}')
                        dir_hist.push(os.getcwd())
                elif tokens[0] == u'cdd' and len(tokens) == 1:
                    pop_dir = dir_hist.pop()
                    if pop_dir == '':
                        print('Reached root of dir stack')
                        continue
                    tokens.append(pop_dir)
                    # show the stack before CD
                    for dir_rec in dir_hist.get_dir_stack():
                        print(f'  {dir_rec}')

                if tokens[0] == u'cdd':
                    tokens[0] = u'cd'
            elif tokens[0] == u'dir':
                if len(tokens) == 2:
                    cmd_arg1 = tokens[1].replace('/', '\\')
                    tokens[1] = cmd_arg1
            elif tokens[0] == u'b':
                # reset the build dir anyway?
                command_cc.set_build_dir_env_var()

            if debug_run:
                tokens.insert(0, u'wdt.cmd')
            # Escape / as \ in app path
            tokens[0] = tokens[0].replace('/', '\\')

            run_command(tokens)

        if not no_history_update:
            # Add to history
            state.history.add(line)
            save_history(state.history.list,
                         pycmd_data_dir + '\\history',
                         max_cmd_history_lines)


            # Add to dir history
            dir_hist.visit_cwd()
            save_history(dir_hist.locations,
                         pycmd_data_dir + '\\dir_history',
                         dir_hist.max_len)

consoleScriptFileName = "pycmd_script.py"

def l(file_name = consoleScriptFileName):
    pycmd_tmp_dir = pycmd_data_dir + '\\tmp'
    pycmd_tmp_script_file = pycmd_tmp_dir + '\\' + file_name
    exec(open(pycmd_tmp_script_file).read(), globals())

def e(file_name = consoleScriptFileName, clearContent = False):
    if len(state.open_app) == 0:
        print("%PYCMD_OPEN_APP% is not configured")
        return

    pycmd_tmp_dir = pycmd_data_dir + '\\tmp'
    pycmd_tmp_script_file = pycmd_tmp_dir + '\\' + file_name
    openEditCmdLine = state.open_app + ' ' + pycmd_tmp_script_file

    scHeaderLine = '#PyConSc ' + str(py_GetConsoleWindow())

    if (not os.path.exists(pycmd_tmp_script_file)) or (clearContent == True):
        with open(pycmd_tmp_script_file, 'w') as scFile:
            # tail # is for set cursor to new line
            scFile.write(scHeaderLine + '\n\n')
        os.system(openEditCmdLine + ' 2')
    else:
        rewriteScFile = True
        with open(pycmd_tmp_script_file, 'r') as scFile:
            if scHeaderLine == scFile.readline().strip():
                rewriteScFile = False

        if rewriteScFile:
            isFirstLine = True
            # file content is cleared upon call to fileinput.input
            for cmdScLine in fileinput.input(pycmd_tmp_script_file, inplace=1):
                if isFirstLine:
                    print(scHeaderLine)
                    isFirstLine = False

                    if not cmdScLine.startswith('#PyConSc '):
                        print(cmdScLine,)
                else:
                    print(cmdScLine,end='')
        # only updates console hwnd, keeps last position
        os.system(openEditCmdLine)

    os.system(state.open_app + ' ' + pycmd_tmp_script_file)


def n(file_name = consoleScriptFileName):
    """clear file console script"""
    e(file_name, True)

def q(obj, name_str) :
    """Query the methods in obj which includes name_str"""
    filtered_list = [i for i in dir(obj) if name_str in i]
    for i in filtered_list:
        print(i)

def py_GetConsoleWindow():
    return ctypes.windll.kernel32.GetConsoleWindow()

def w(write_str):
    """Write customize string to command line file for expanding"""
    if len(write_str) > 0:
        write_str_strip = write_str.strip()
        if len(write_str_strip):
            with open(cmdLineFilePath, 'w') as cmdFile:
                cmdFile.write(write_str_strip)

PyCmd_InternalCmds = [l, e, n, w]
def pcr():
    """Recover PyCmd internal commands"""
    global l, e, n, w
    l, e, n, w = PyCmd_InternalCmds

def cls():
    """Clear screen on Windows"""
    os.system('cls')


def resolve_path_case(path):
    casePath = str(pathlib.Path(path.decode('utf-8')).resolve(strict=True))
    return casePath

def internal_cd(args):
    """The internal CD command"""
    try:
        if len(args) == 0:
            to_dir = expand_env_vars('~').encode()
        else:
            target = args[0]
            if target != u'\\' and target[1:] != u':\\':
                target = target.rstrip(u'\\')
            target = expand_env_vars(target.strip(u'"').strip(u' '))
            to_dir = target.encode(sys.getfilesystemencoding())
        to_dir = resolve_path_case(to_dir)
        os.chdir(to_dir)
        WindowSwitch.update_window_state(to_dir)
    except OSError as error:
        stdout.write(u'\n' + str(error).replace('\\\\', '\\'))
    os.environ['CD'] = os.getcwd()


def internal_exit(message = ''):
    """The EXIT command, with an optional goodbye message"""
    deinit()
    WindowSwitch.update_window_state('', '')
    if ((not behavior.quiet_mode) and message != ''):
        print(message)
    sys.exit()


def run_command(tokens):
    """Execute a command line (treat internal and external appropriately"""
    if tokens[0] == 'exit':
        internal_exit('Bye!')
    elif tokens[0].lower() == 'cd' and [t for t in tokens if t in sep_tokens] == []:
        # This is a single CD command -- use our custom, more handy CD
        internal_cd([unescape(t) for t in tokens[1:]])
    else:
        WindowSwitch.update_window_state('', ' '.join(tokens))
        if set(sep_tokens).intersection(tokens) == set([]):
            # This is a simple (non-compound) command
            # Crude hack so that we return to the prompt when starting GUI
            # applications: if we think that the first token on the given command
            # line is an executable, check its PE header to decide whether it's
            # GUI application. If it is, spawn the process and then get on with
            # life.
            cmd = expand_env_vars(tokens[0].strip('"'))
            dir, name = os.path.split(cmd)
            ext = os.path.splitext(name)[1]

            if ext in ['', '.exe', '.com', '.bat', '.cmd']:
                # Executable given
                app = cmd
            else:
                # Not an executable -- search for the associated application
                if os.path.isfile(cmd):
                    app = associated_application(ext)
                else:
                    # No application will be spawned if the file doesn't exist
                    app = None

            if app:
                executable = full_executable_path(app)
                if executable and os.path.splitext(executable)[1].lower() == '.exe':
                    # This is an exe file, try to figure out whether it's a GUI
                    # or console application
                    if is_gui_application(executable):
                        import subprocess
                        s = u' '.join([expand_tilde(t) for t in tokens])
                        subprocess.Popen(s.encode(sys.getfilesystemencoding()), shell=True)
                        return

        # Regular (external) command
        start_time = time.time()
        run_in_cmd(tokens)
        console_window = ctypes.windll.kernel32.GetConsoleWindow()
        if ctypes.windll.user32.GetForegroundWindow() != console_window and time.time() - start_time > 15:
            # If the window is inactive, flash after long tasks
            flashwinfo = console.USER32_FLASHWINFO()
            flashwinfo.Size = ctypes.sizeof(console.USER32_FLASHWINFO)
            flashwinfo.hwnd = console_window
            flashwinfo.flags = 0x3 # FLASHW_ALL
            flashwinfo.count = 3
            flashwinfo.Timeout = 750
            ctypes.windll.user32.FlashWindowEx(ctypes.byref(flashwinfo))

def run_in_cmd(tokens):
    pseudo_vars = ['CD', 'DATE', 'ERRORLEVEL', 'RANDOM', 'TIME']

    expand_env = False if tokens[0] == 'sd' else True

    line_sanitized = ''
    for token in tokens:
        token_sane = expand_tilde(token) if expand_env else token
        if token_sane != '\\' and token_sane[1:] != ':\\':
            token_sane = token_sane.rstrip('\\')
        if token_sane.count('"') % 2 == 1:
            token_sane += '"'
        line_sanitized += token_sane + ' '
    line_sanitized = line_sanitized[:-1]
    if line_sanitized.endswith('&') and not line_sanitized.endswith('^&'):
        # We remove a redundant & to avoid getting an 'Unexpected &' error when
        # we append a new one below; the ending & it would be ignored by cmd.exe
        # anyway...
        line_sanitized = line_sanitized[:-1]
    elif line_sanitized.endswith('|') and not line_sanitized.endswith('^|') \
            or line_sanitized.endswith('&&') and not line_sanitized.endswith('^&&'):
        # The syntax of the command is incorrect, cmd would refuse to execute it
        # altogether; in order to we replicate the error message, we run a simple
        # invalid command and return
        stdout.write('\n')
        os.system('echo |')
        return

    # Cleanup environment
    for var in pseudo_vars:
        if var in os.environ.keys():
            del os.environ[var]

    # Run command
    if line_sanitized != '':
        command = u'"'
        command += line_sanitized
        command += u' &set > "' + tmpfile + u'"'
        for var in pseudo_vars:
            command += u' & echo ' + var + u'="%' + var + u'%" >> "' + tmpfile + '"'
        command += u'& <nul (set /p xxx=CD=) >>"' + tmpfile + u'" & cd >>"' + tmpfile + '"'
        command += u'"'
        os.system(command) #.encode(sys.getfilesystemencoding()))

    # Update environment and state
    new_environ = {}
    env_file = open(tmpfile, 'r')
    for l in env_file.readlines():
        [variable, value] = l.split('=', 1)
        value = value.rstrip('\n ')
        if variable in pseudo_vars:
            value = value.strip('"')
        new_environ[variable] = value
    env_file.close()
    if new_environ != {}:
        for variable in os.environ.keys():
            if not variable in new_environ.keys() \
                   and sorted(new_environ.keys()) != sorted(pseudo_vars):
                del os.environ[variable]
        for variable in new_environ:
            os.environ[variable] = new_environ[variable]
    cd = os.environ['CD'] # .decode(stdout.encoding)
    os.chdir(cd.encode(sys.getfilesystemencoding()))


def signal_handler(signum, frame):
    """
    Signal handler that catches SIGINT and emulates the Ctrl-C
    keyboard combo
    """
    if signum == signal.SIGINT:
        # Emulate a Ctrl-C press
        write_input(67, 0x0008)

def append_tail_datetime(line):
    return line + datetime.datetime.now().strftime("[%Y/%m/%d %I:%M:%S%p %A]")

def remove_tail_datetime(line):
    # empty line slips in by crashing pycmd?
    if len(line) == 0:
        return ''
    if line[-1] == u']':
        i = len(line) - 4
        if i > 0 and line[i] == u'd' and line[i+1] == u'a' and line[i+2] == u'y':
            i -= 26
            for j in range(4):
                k = i - j
                if k > 0:
                    if line[k] == u'[':
                        return line[:k]
                else:
                    break;
    # no tail datetime found
    return line

def save_history(lines, filename, length):
    """
    Save a list of unique lines into a history file and truncate the
    result to the given maximum number of lines
    """
    if os.path.isfile(filename):
        # Read previously saved history and merge with current
        history_file = codecs.open(filename, 'r', 'utf8', 'replace')
        history_to_save = [line.rstrip(u'\n') for line in history_file.readlines()]
        history_file.close()
        # For performance and correctness of merging history from multiple instances,
        # only save the last command, this is good because save_history is called after
        # each command
        if len(history_to_save) > 0 and lines[-1] == remove_tail_datetime(history_to_save[-1]):
            # no update
            return

        # assume duplicated could happen at most once
        for histI in range(len(history_to_save)-2, -1, -1):
            if remove_tail_datetime(history_to_save[histI]) == lines[-1]:
                del history_to_save[histI]
                break
        history_to_save.append(append_tail_datetime(lines[-1]))
        # for line in lines:
        #     if line in history_to_save:
        #         history_to_save.remove(line)
        #     history_to_save.append(line)
    else:
        # No previous history, save current
        history_to_save = lines

    if len(history_to_save) > length:
        history_to_save = history_to_save[-length :]    # Limit history file

    # Write merged history to history file
    history_file = codecs.open(filename, 'w', 'utf8')
    history_file.writelines([line + u'\n' for line in history_to_save])
    history_file.close()


def read_history(filename):
    """
    Read and return a list of lines from a history file
    """
    if os.path.isfile(filename):
        history_file = codecs.open(filename, 'r', 'utf8', 'replace')
        history = [remove_tail_datetime(line.rstrip(u'\n\r')) for line in history_file.readlines()]
        history_file.close()
    else:
        print('Warning: Can\'t open ' + os.path.basename(filename) + '!')
        history = []
    return history


def print_usage():
    """Print usage information"""
    print('Usage:')
    print('\t PyCmd [-i script] [-t title] ( [-c command] | [-k command] | [-h] )')
    print()
    print('\t\t-c command \tRun command, then exit')
    print('\t\t-k command \tRun command, then continue to the prompt')
    print('\t\t-t title \tShow title in window caption')
    print('\t\t-i script \tRun additional init/config script')
    print('\t\t-q\t\tQuiet (suppress messages)')
    print('\t\t-h \t\tShow this help')
    print()
    print('Note that you can use \'/\' instead of \'-\', uppercase instead of ')
    print('lowercase and \'/?\' instead of \'-h\'')


# Entry point
if __name__ == '__main__':
    try:
        init()
        main()
    except Exception as e:        
        report_file_name = (pycmd_data_dir
                            + '\\crash-' 
                            + time.strftime('%Y%m%d_%H%M%S') 
                            + '.log')
        print()
        print('************************************')
        print('PyCmd has encountered a fatal error!')
        print()
        report_file = open(report_file_name, 'w')
        traceback.print_exc(file=report_file)
        report_file.close()
        traceback.print_exc()
        print() 
        print('Crash report written to:\n  ' + report_file_name)
        print()
        print('Press any key to exit... ')
        print('************************************')
        read_input()
