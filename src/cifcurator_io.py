import sys, os, shutil, datetime
#

def check_project(projdir=None, level='top', action='create', verbose=True):
    """
    Manages the project directory by creating, cleaning, or deleting directories.

    Parameters:
    -----------
    projdir : str, optional
      The path to the project directory. If None, a message will display asking to provide the path.
    level : str, optional
      Specifies the directory level. Default is 'top', meaning the project directory itself.
      You can specify a subdirectory within the project directory.
    action : str, optional
      The action to perform on the directory. Options are:
      - 'create': Create the directory if it doesn't already exist.
      - 'clean': Remove all files in the directory, leaving it empty.
      - 'delete': Deletes the directory and everything within it.
    verbose : bool, optional
      If True, prints informative messages about the actions being performed. Default is True.

    Returns:
    --------
    None
    """

    if projdir is None:
        print("Please provide a project directory path")
    else:
        dirname = projdir
        if(level!='top'):
            dirname=dirname+'/'+level
        if(action=='create'):
            create_dir(dirname, verbose=verbose)
        elif(action=='clean'):
            clean_dir(dirname, verbose=verbose)
        elif(action=='delete'):
            delete_dir(dirname, verbose=verbose)

def create_dir(dirpath, verbose=True):
    """
    Creates a directory if it does not exist, and writes a creation timestamp in 'info.txt'.

    Parameters:
    -----------
    dirpath : str
       The path of the directory to create.
    verbose : bool, optional
       If True, prints informative messages about the action taken. Default is True.

    Returns:
    --------
    None
    """

    if not os.path.exists(dirpath):
        os.mkdir(dirpath)
        if verbose:
            now=datetime.datetime.now()
            f = open(dirpath+'/info.txt', 'w')
            f.write('directory created on {0}'.format(now))
            f.close()
    else:
        if verbose:
            print('{0} already exists, with content:'.format(dirpath))
            print(os.listdir(dirpath))
            
def clean_dir(dirpath, verbose=True):
    """
    Removes all files from the specified directory, leaving it empty.

    Parameters:
    -----------
    dirpath : str
       The path of the directory to clean.
    verbose : bool, optional
       If True, a message is printed regarding the action taken. Default is True.

    Returns:
    --------
    None
    """

    if os.path.exists(dirpath):
        listfile = (file for file in os.listdir(dirpath) if os.path.isfile(os.path.join(dirpath, file)))
        if verbose:
            print('Cleaning {0}...'.format(dirpath))
        for f in listfile:
            os.remove(dirpath+'/'+f)

def delete_dir(dirpath, verbose=True):
    """
    Deletes the specified directory and all of its contents.

    Parameters:
    -----------
    dirpath : str
       The path of the directory to delete.
    verbose : bool, optional
       If True, a message is printed regarding the action taken. Default is True.

    Returns:
    --------
    None
    """

    if os.path.exists(dirpath):
        shutil.rmtree(dirpath)
        if verbose:
            print('Deleting {0}...'.format(dirpath))
