import sys, os
import PyCmd

def run(tokens):
    if len(tokens) == 0:
        # default to cd(change directory)
        cd_to_dir(tokens)
        return

    if tokens[0] == 'd':
        run_cmd = 'rd /s/q .'
    elif tokens[0] == 'c':
        run_cmd = 'del CMakeCache.txt'
    else:
        print(f'\nUnknown command {tokens[0]}')
        return
    
    proj_name, dir_type = get_proj_and_type()
    if dir_type > 0:
        print(f'\nrun "{run_cmd}" in cwd\n')
        os.system(f'cmd.exe /c {run_cmd}')
    else:
        # remove the default output dir
        to_dir = get_to_dir(-1)
        if len(to_dir) > 0 and os.path.isdir(to_dir):
            print(f'\nrun "{run_cmd}" in {to_dir}\n')
            orig_dir = os.getcwd()
            os.chdir(to_dir)
            os.system(f'cmd.exe /c {run_cmd}')
            os.chdir(orig_dir)
    
def cd_to_dir(tokens):
    to_dir_id = -1
    if len(tokens) > 0 and tokens.isnumeric():
        to_dir_id = int(tokens)

    to_dir = get_to_dir(to_dir_id)
    if len(to_dir) > 0:
        PyCmd.internal_cd([to_dir])
    else:
        print("\nNot in source or build dir?")

def expand_path(dir_id):
    cwd = os.getcwd()
    cwd_basename = os.path.basename(cwd)
    if cwd_basename.startswith('rune_'):
        # For Rust project
        exe_path = os.path.join(cwd, 'target', 'debug', cwd_basename[5:] + '.exe')
        if os.path.isfile(exe_path):
            return exe_path
        exe_path = os.path.join(cwd, 'target', 'release', cwd_basename[5:] + '.exe')
        if os.path.isfile(exe_path):
            return exe_path
        return ''
    else:
        return get_to_dir(dir_id)

# dir_id -1 -> auto switch between source and 0
# dir_id 0 -> build dir
# TODO dir_id 0 always returns empty?
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
                    os.makedirs(to_dir)
                else:
                    print(f"\n expected build dir {to_dir} is a file?")
                    # to_dir = ''
            if not 'PYCMD_BUILD_DIR' in os.environ:
                os.environ['PYCMD_BUILD_DIR'] = to_dir
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

def set_build_dir_env_var():
    curr_dir, pri_git_dir, pri_git_build_dir = get_path()
    proj_name, dir_type = get_proj_and_type()

    if len(proj_name) == 0 or dir_type == -1:
        # don't leave it as empty once called set_build_dir_env_var
        os.environ['PYCMD_BUILD_DIR'] = 'not_in_source_or_build_dir'
        return

    build_dir = os.path.join(pri_git_build_dir, proj_name)
    if not os.path.isdir(build_dir):
        if not os.path.isfile(build_dir):
            # TODO check makedirs failed
            os.makedirs(build_dir)
        else:
            print(f"\n expected build dir {build_dir} is a file?")
    os.environ['PYCMD_BUILD_DIR'] = build_dir

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
    elif curr_dir_lower.startswith(pri_git_build_dir_lower + os.sep):
        dir_type = 1
        proj_name = curr_dir[len(pri_git_build_dir)+1:]
        if (sep_pos := proj_name.find(os.sep)) != -1:
            proj_name = proj_name[:sep_pos]
        if (sep_pos := proj_name.find('.')) != -1:
            proj_name = proj_name[:sep_pos]

    return proj_name, dir_type

def complete_suggestion_for_cc(clean_bin=False):
    complete_str = ''

    if not 'VSINSTALLDIR' in os.environ:
        print('\nRun vcvarsall.bat first!\n')
        return complete_str

    (proj_name, dir_type) = get_proj_and_type()
    if dir_type >= 0:
                # set build out dir
        if 'PRIGIT_B' in os.environ:
            out_dir = os.path.join(os.environ['PRIGIT_B'], proj_name)
        else:
            out_dir = os.path.join(os.environ['PRIGIT'] + '_b', proj_name)

        complete_str += f'rd /s/q {out_dir} & cmake ' if clean_bin else '' 

        source_dir = os.path.join(os.environ['PRIGIT'], proj_name)
        # Don't add -S if CMakeLists.txt doesn't exist, assume current dir is source dir
        if os.path.isfile(os.path.join(source_dir, 'CMakeLists.txt')):
            complete_str += f'-S {source_dir}'
       
        ## hack for LLVM, where the build root source dir is under a subdir llvm.
        if proj_name.lower() == 'llvm':
            complete_str += os.sep + 'llvm'


        complete_str += f' -B {out_dir}'

        os.environ['PYCMD_BUILD_DIR'] = out_dir

        # TODO, support multiple config
        init_cache = os.path.join(os.environ['PRIGIT'], 'cc', proj_name + '.cmake')
        if os.path.isfile(init_cache):
            complete_str += f' -C {init_cache}'
        else:
            complete_str += f' -G Ninja'

            vcpkg_root = os.path.join(os.environ['PRIGIT'], 'vcpkg')
            if os.path.isdir(vcpkg_root):
                complete_str += f' -D CMAKE_TOOLCHAIN_FILE={vcpkg_root}/scripts/buildsystems/vcpkg.cmake'

        complete_str += ' && b'

    return complete_str
