"""Run the public J71t userspace headlessly in Podman; never access an iPad."""
from release.j71b.smoke_desktop import main

if __name__ == '__main__':
    main('j71t')
