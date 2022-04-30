import sys, os
import PyCmd

def run(tokens):
    cd_to_dir(tokens)
    
def cd_to_dir(tokens):
    curr_dir = os.getcwd()
    pri_git_path = os.environ['PRIGIT']
    pri_git_build_path = pri_git_path+'b'
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
    # TODO: support Linux which is case sensitive?
    curr_dir = os.getcwd()
    pri_git_path = os.environ['PRIGIT']
    pri_git_build_path = pri_git_path+'b'

    curr_dir_lower = curr_dir.lower()
    pri_git_path_lower = pri_git_path.lower()
    pri_git_build_path_lower = pri_git_path.lower()+'b'

    proj_name = ''
    dir_type = -1

    if curr_dir_lower.startswith(pri_git_path_lower + os.sep):
        dir_type = 0
        proj_name = curr_dir[len(pri_git_path)+1:]
        if (sep_pos := proj_name.find(os.sep)) != -1:
            proj_name = proj_name[:sep_pos]
    elif curr_dir.startswith(pri_git_build_path_lower + os.sep):
        dir_type = 1
        proj_name = curr_dir[len(pri_git_build_path)+1:]
        if (sep_pos := proj_name.find(os.sep)) != -1:
            proj_name = proj_name[:sep_pos]
        if (sep_pos := proj_name.find('.')) != -1:
            proj_name = proj_name[:sep_pos]

    if len(proj_name) == 0 or dir_type == -1:
        return ''

    to_dir = ''
    if dir_id == -1:
        if dir_type == 0:
            to_dir = os.path.join(pri_git_build_path, proj_name)
            if not os.path.isdir(to_dir):
                if not os.path.isfile(to_dir):
                    os.mkdir(to_dir)
                else:
                    print(f"\n expected build dir {to_dir} is a file?")
                    # to_dir = ''
        elif dir_type == 1:
            to_dir = os.path.join(pri_git_path, proj_name)
            if not os.path.isdir(to_dir):
                print(f"\nHow could this happen, source dir doesn't exist?")

    return to_dir

