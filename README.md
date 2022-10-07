# lpt

## Install

```
poetry install
```

## Run analysis using existing logs

```
poetry run lpt analyze-journal --journal-path tests/data/one-boot/journal.txt
poetry run lpt analyze-cloudinit --cloudinit-log-path tests/data/one-boot/cloud-init.log
poetry run lpt analyze --journal-path tests/data/one-boot/journal.txt --cloudinit-log-path tests/data/one-boot/cloud-init.log
```

## Run analysis on local system

```
poetry run lpt analyze
poetry run lpt analyze --boot
```
