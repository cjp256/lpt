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
lpt analyze-journal --journal-path tests/data/one-boot/journal.txt
lpt analyze-cloudinit --cloudinit-log-path tests/data/one-boot/cloud-init.log
lpt analyze --journal-path tests/data/one-boot/journal.txt --cloudinit-log-path tests/data/one-boot/cloud-init.log
```

## Run analysis on local system

```
lpt analyze
lpt analyze --boot
```
