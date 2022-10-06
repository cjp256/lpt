# lpt

## Install

```
poetry install
```

## Run analysis using existing logs

```
poetry run lpt analyze --journal-json-path tests/data/single-instance/journal.txt  --cloudinit-log-path tests/data/single-instance/cloud-init.log
```

## Run analysis on local system

```
poetry run lpt analyze --journal-json-path local --cloudinit-log-path local
```
