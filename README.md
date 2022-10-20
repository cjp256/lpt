# lpt

## Install

With poetry:
```
poetry install
```

With pip:
```
pip install git+https://github.com/cjp256/lpt
```

## Run analysis using existing logs

```
lpt --journal-path tests/data/one-boot/journal.txt analyze-journal
lpt --cloudinit-log-path tests/data/one-boot/cloud-init.log analyze-cloudinit
lpt --journal-path tests/data/one-boot/journal.txt --cloudinit-log-path tests/data/one-boot/cloud-init.log analyze
```

## Run analysis on local system

```
lpt analyze
lpt analyze --boot
```

## Graph system dependencies

```
lpt graph --service ssh.service --filter-conditional-result-no --filter-service systemd-journald.socket
```

## Remote anaylsis

```
lpt --debug --ssh-proxy-host 10.144.133.148 --ssh-proxy-user cpatterson --ssh-host test-u1804m-x1.eastus.cloudapp.azure.com --ssh-user cpatterson analyze
```
