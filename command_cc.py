import sys, os
import PyCmd

def run(tokens):
    if len(tokens) == 1 and tokens[0] == 'c':
        proj_name, dir_type = get_proj_and_type()
        if dir_type > 0:
            print("\nrun rd /s/q .")
            os.system('cmd.exe /c rd /s/q .')
        else:
            print("\nThe cc clear command is only for build dir")
    else:
        # default to cd(change directory)
        cd_to_dir(tokens)
    
def cd_to_dir(tokens):
    to_dir_id = -1
    if len(tokens) > 0 and tokens.isnumeric():
        to_dir_id = int(tokens)

    to_dir = get_to_dir(to_dir_id)
    if len(to_dir) > 0:
        PyCmd.internal_cd([to_dir])
    else:
        print("\nNot in source or build dir?")

# -1 -> auto switch between source and 0
# 0 -> build dir
def get_to_dir(dir_id):
    curr_dir, pri_git_dir, pri_git_build_dir = get_path()

    proj_name, dir_type = get_proj_and_type()

    #TODO, for source dir, check CMakeLists.txt exists before switching?

    if len(proj_name) == 0 or dir_type == -1:
        return ''

    to_dir = ''
    if dir_id == -1:
        # in source dir
        if dir_type == 0:
            to_dir = os.path.join(pri_git_build_dir, proj_name)
            if not os.path.isdir(to_dir):
                if not os.path.isfile(to_dir):
                    os.mkdir(to_dir)
                else:
                    print(f"\n expected build dir {to_dir} is a file?")
                    # to_dir = ''
        # in build dir
        # TODO: is switch back to the top of source dir useful, instead of back to the prev dir in source?
        elif dir_type == 1:
            to_dir = os.path.join(pri_git_dir, proj_name)
            if not os.path.isdir(to_dir):
                print(f"\nHow could this happen, source dir doesn't exist?")
        elif dir_type > 1:
            # TODO, support multiple build profiles
            pass

    return to_dir

def get_path():
    curr_dir = os.getcwd()
    pri_git_dir = os.environ['PRIGIT']
    pri_git_build_dir = pri_git_dir + '_b'

    return curr_dir, pri_git_dir, pri_git_build_dir

# dir_type: 0 -> source
#           1 -> build
def get_proj_and_type():
    curr_dir, pri_git_dir, pri_git_build_dir = get_path()

    curr_dir_lower = curr_dir.lower()
    pri_git_dir_lower = pri_git_dir.lower()
    pri_git_build_dir_lower = pri_git_build_dir.lower()

    proj_name = ''
    dir_type = -1

    if curr_dir_lower.startswith(pri_git_dir_lower + os.sep):
        dir_type = 0
        proj_name = curr_dir[len(pri_git_dir)+1:]
        if (sep_pos := proj_name.find(os.sep)) != -1:
            proj_name = proj_name[:sep_pos]
    elif curr_dir.startswith(pri_git_build_dir_lower + os.sep):
        dir_type = 1
        proj_name = curr_dir[len(pri_git_build_dir)+1:]
        if (sep_pos := proj_name.find(os.sep)) != -1:
            proj_name = proj_name[:sep_pos]
        if (sep_pos := proj_name.find('.')) != -1:
            proj_name = proj_name[:sep_pos]

    return proj_name, dir_type

def complete_suggestion_for_cc():
    complete_str = ''
    (proj_name, dir_type) = get_proj_and_type()
    if dir_type > 0:
        source_dir = os.path.join(os.environ['PRIGIT'], proj_name)
        complete_str += f'-S {source_dir}'
        # TODO, support multiple config
        init_cache = os.path.join(os.environ['PRIGIT'], 'cc', proj_name + '.cmake')
        if os.path.isfile(init_cache):
            complete_str += f' -C {init_cache}'

    return complete_str
