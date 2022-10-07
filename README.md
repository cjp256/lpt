# lpt

## Install

```
poetry install
```

## Run analysis using existing logs

```
poetry run lpt analyze --journal-json-path tests/data/one-boot/journal.txt  --cloudinit-log-path tests/data/one-boot/cloud-init.log
poetry run lpt analyze --journal-json-path tests/data/two-boot/journal.txt  --cloudinit-log-path tests/data/two-boot/cloud-init.log
```

## Run analysis on local system

```
poetry run lpt analyze --journal-json-path local --cloudinit-log-path local
```
