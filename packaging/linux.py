"""Native Linux packages sharing the same tested portable payload."""

import platform
import shutil
import subprocess


def packages(directory, output, version):
    machine = platform.machine().lower()
    deb_arch = 'arm64' if machine in {'aarch64', 'arm64'} else 'amd64'
    rpm_arch = 'aarch64' if deb_arch == 'arm64' else 'x86_64'
    stage = output / 'linux-stage'
    if stage.exists():
        shutil.rmtree(stage)
    shutil.copytree(directory, stage / 'opt/agentverse')
    script = stage / 'usr/bin/agentverse'
    script.parent.mkdir(parents=True)
    script.write_text('#!/bin/sh\nexec /opt/agentverse/agentverse "$@"\n')
    script.chmod(0o755)
    desktop = stage / 'usr/share/applications/agentverse.desktop'
    desktop.parent.mkdir(parents=True)
    desktop.write_text('[Desktop Entry]\nType=Application\nName=AgentVerse\nExec=/opt/agentverse/agentverse\nTerminal=false\nCategories=Development;\n')
    (stage / 'DEBIAN').mkdir()
    (stage / 'DEBIAN/control').write_text(f'Package: agentverse\nVersion: {version}\nArchitecture: {deb_arch}\nMaintainer: AgentVerse maintainers\nDepends: libc6 (>= 2.39)\nSection: devel\nPriority: optional\nDescription: Shared workspace for independent agent teams\n Python and the dashboard are included; coding tools are installed separately.\n')
    subprocess.run(['dpkg-deb', '--root-owner-group', '--build', str(stage), str(output / f'agentverse-{version}-linux-{deb_arch}.deb')], check=True)
    if not shutil.which('rpmbuild'):
        raise ValueError('Install rpm build tools to produce the complete native Linux release.')
    rpm = output / 'rpm-build'
    for folder in ('BUILD', 'RPMS', 'SOURCES', 'SPECS', 'SRPMS', 'BUILDROOT'):
        (rpm / folder).mkdir(parents=True, exist_ok=True)
    spec = rpm / 'SPECS/agentverse.spec'
    spec.write_text(f'''Name: agentverse
Version: {version}
Release: 1
Summary: Shared workspace for independent agent teams
License: MIT
BuildArch: {rpm_arch}
Requires: glibc >= 2.39
AutoReqProv: no
%description
AgentVerse bundles Python and its dashboard. Coding tools are installed separately.
%install
mkdir -p %{{buildroot}}/opt %{{buildroot}}/usr/bin %{{buildroot}}/usr/share/applications
cp -a "{directory}" %{{buildroot}}/opt/agentverse
cp "{script}" %{{buildroot}}/usr/bin/agentverse
cp "{desktop}" %{{buildroot}}/usr/share/applications/agentverse.desktop
%files
/opt/agentverse
/usr/bin/agentverse
/usr/share/applications/agentverse.desktop
''')
    subprocess.run(['rpmbuild', '--define', '_topdir ' + str(rpm.resolve()), '--define', '_build_id_links none',
                    '--define', '__os_install_post %{nil}', '-bb', str(spec)], check=True)
    for package in rpm.rglob('*.rpm'):
        shutil.copy2(package, output / package.name)
