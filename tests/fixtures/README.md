# Fixture provenance

- `sample.dbc` and `sample_changed.dbc` are purpose-written for this repository.
  They describe fictional nodes, messages, and signals and contain no production
  or customer data. Their two extended IDs intentionally match frames in the log
  fixtures so integration tests can exercise composition.
- `invalid.dbc` is a purpose-written malformed model used to pin structured
  validation output. It contains no external data.
- `candump/candump.log` is copied byte-for-byte from capkit 0.2.0. It is the same
  300 anonymized frames serialized to the can-utils `candump -L` dialect by
  python-can 4.6.1's `CanutilsLogWriter` and round-trip checked with its
  `CanutilsLogReader`. Timestamps are epoch seconds.
- `vector_asc/python_can_logfile.asc` is copied byte-for-byte from capkit 0.2.0,
  which sources `test/data/logfile.asc` from
  [`hardbyte/python-can`](https://github.com/hardbyte/python-can) commit
  `b4f82abede25ff83376be793a2935c41f81c3869`. It is licensed under LGPL-3.0;
  see `vector_asc/LICENSE.python-can.txt`.
