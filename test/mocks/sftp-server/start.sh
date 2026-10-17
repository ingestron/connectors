#!/bin/sh
set -eu
rm -f /etc/ssh/ssh_host_*_key /etc/ssh/ssh_host_*_key.pub
ssh-keygen -A >/dev/null 2>&1
mkdir -p /run/sshd /home/reader/.ssh/keys /home/reader/upload
chown root:root /home/reader
chown reader:reader /home/reader/.ssh /home/reader/.ssh/keys
chmod 755 /home/reader
chmod 700 /home/reader/.ssh /home/reader/.ssh/keys
chown reader:reader /home/reader/.ssh/keys/fixture.pub
chmod 644 /home/reader/.ssh/keys/fixture.pub
exec /usr/sbin/sshd -D -e -f /etc/ssh/sshd_config.fixture
