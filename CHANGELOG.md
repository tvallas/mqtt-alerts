# CHANGELOG

<!-- version list -->

## v0.4.7 (2026-08-11)

### Bug Fixes

- **ci**: Limit Trivy image scan to OS vulnerabilities
  ([`65f85e3`](https://github.com/tvallas/mqtt-alerts/commit/65f85e344eec31e3116d4e150527635aae71307f))


## v0.4.6 (2026-08-11)

### Bug Fixes

- **deps**: Bump the python-minor-patch group across 1 directory with 3 updates
  ([`958ef0a`](https://github.com/tvallas/mqtt-alerts/commit/958ef0ab383921c139cef965d9f93a6550e5ac8f))

### Chores

- **deps**: Bump actions/checkout from 6 to 7
  ([`a53f88e`](https://github.com/tvallas/mqtt-alerts/commit/a53f88e1e79330b2864003198c8e417b8485611c))


## v0.4.5 (2026-05-23)

### Bug Fixes

- **deps**: Bump black in the python-minor-patch group
  ([`1f67056`](https://github.com/tvallas/mqtt-alerts/commit/1f6705610513f15108ddf4d5c8ec58ea56681b2b))


## v0.4.4 (2026-05-09)

### Bug Fixes

- **docker**: Upgrade runtime pip before wheel install
  ([`f459de3`](https://github.com/tvallas/mqtt-alerts/commit/f459de39d6d7173b3b7108bb78ad9382cc81a3ef))

### Chores

- **deps**: Bump aquasecurity/trivy-action
  ([`607f3b1`](https://github.com/tvallas/mqtt-alerts/commit/607f3b116217933f23e5378c0a34b977eb1fb211))


## v0.4.3 (2026-04-23)

### Bug Fixes

- **changelog**: Restore release history
  ([`a3e6bf9`](https://github.com/tvallas/mqtt-alerts/commit/a3e6bf95a12d8b8e8dca2e8b598de4c81907ebe9))

### Chores

- Add aggregate verification target
  ([`ed94714`](https://github.com/tvallas/mqtt-alerts/commit/ed94714c0a9d0d29109503d518d08ca98f5f21ee))

### Continuous Integration

- Enforce conventional commit messages
  ([`582addd`](https://github.com/tvallas/mqtt-alerts/commit/582addd1ddf28f1032b8ecefc580adc56be42548))

### Documentation

- Add repository contributor guidance
  ([`9422578`](https://github.com/tvallas/mqtt-alerts/commit/942257870aa532eaffd7e8a55318048cf6adb103))


## Unreleased

### Chores

- Add aggregate verification target
  ([`ed94714`](https://github.com/tvallas/mqtt-alerts/commit/ed94714c0a9d0d29109503d518d08ca98f5f21ee))

### Continuous Integration

- Enforce conventional commit messages
  ([`582addd`](https://github.com/tvallas/mqtt-alerts/commit/582addd1ddf28f1032b8ecefc580adc56be42548))

### Documentation

- Add repository contributor guidance
  ([`9422578`](https://github.com/tvallas/mqtt-alerts/commit/942257870aa532eaffd7e8a55318048cf6adb103))


## v0.4.2 (2026-04-21)

### Bug Fixes

- Support multiple value fields per MQTT topic
  ([`339e93a`](https://github.com/tvallas/mqtt-alerts/commit/339e93afe7574d3624109bb73f420599435f21d9))

### Chores

- **release**: 0.4.2
  ([`f17f7f1`](https://github.com/tvallas/mqtt-alerts/commit/f17f7f1dcecb483b9a3dae02c039c5af40a4ee96))

### Testing

- Cover shared-topic sensor value fields
  ([`d242988`](https://github.com/tvallas/mqtt-alerts/commit/d24298847f39adea95738c78a8620bf429116a1c))


## v0.4.1 (2026-04-21)

### Bug Fixes

- Align packaging metadata with MIT licensing rules
  ([`e3b6274`](https://github.com/tvallas/mqtt-alerts/commit/e3b6274131190027a6619e722fac221d8086e453))

### Chores

- **release**: 0.4.1
  ([`d2eb32c`](https://github.com/tvallas/mqtt-alerts/commit/d2eb32cd68982dba188a31769efabac23e192db8))

### Documentation

- Add comprehensive documentation under docs
  ([`0367b31`](https://github.com/tvallas/mqtt-alerts/commit/0367b318913a86caea00097420f2178fdc0ffdc5))

- Crop logo whitespace for README rendering
  ([`eba60ca`](https://github.com/tvallas/mqtt-alerts/commit/eba60caf4ece9a87bd06a7400f5353aac88af136))

- Refresh README layout and backend overview
  ([`14c539f`](https://github.com/tvallas/mqtt-alerts/commit/14c539f6cd190a796050f89ff90bcd825ff8f38d))

- Use explicit python and MIT badges in README
  ([`1692cc0`](https://github.com/tvallas/mqtt-alerts/commit/1692cc01a10c0e2b440ade0585963ba1fd080906))


## v0.4.0 (2026-04-21)

### Bug Fixes

- Make Telegram acknowledgements idempotent
  ([`ae24e28`](https://github.com/tvallas/mqtt-alerts/commit/ae24e2840cbdd369a709b63dd48ea7e95fd666fb))

### Chores

- Refresh lockfile and ignore ntfy config
  ([`3940f63`](https://github.com/tvallas/mqtt-alerts/commit/3940f634bfc9fc5d1bb23051e3d83a8d8f065f45))

- **release**: 0.4.0
  ([`d3576ae`](https://github.com/tvallas/mqtt-alerts/commit/d3576ae53bc4b1cca7dd274c24589a74415173c5))

### Documentation

- Document Telegram alert reminders
  ([`8c7445a`](https://github.com/tvallas/mqtt-alerts/commit/8c7445aa00f05699705f8644e0e4a15917c3506d))

### Features

- Add Telegram alert reminders
  ([`371f5a3`](https://github.com/tvallas/mqtt-alerts/commit/371f5a3c1e4d635dde4481ed56ede62978e3e80d))


## v0.3.0 (2026-04-20)

### Bug Fixes

- Restore python 3.10 datetime compatibility
  ([`c6487fb`](https://github.com/tvallas/mqtt-alerts/commit/c6487fbeb34b69ca09460bcf6c10892c3b26de38))

### Chores

- **deps**: Bump docker/build-push-action from 6 to 7
  ([`0cf4311`](https://github.com/tvallas/mqtt-alerts/commit/0cf431185c55ac43c4a9f66628d4ebd05ca843d8))

- **deps**: Bump docker/login-action from 3 to 4
  ([`fb2ecd8`](https://github.com/tvallas/mqtt-alerts/commit/fb2ecd88687445b1f790a3b2170cbce7bfd83818))

- **release**: 0.3.0
  ([`114c804`](https://github.com/tvallas/mqtt-alerts/commit/114c8040e04526980d12f1d6b3818eeb83ae45c2))

### Documentation

- Explain telegram alert lifecycle
  ([`e198cc9`](https://github.com/tvallas/mqtt-alerts/commit/e198cc98af4a603c377d05a21fd554ddb6aaca20))

### Features

- Add telegram acknowledgements
  ([`b2b9f12`](https://github.com/tvallas/mqtt-alerts/commit/b2b9f125ed39ca46d571cdf9d0f6b586102c2d9e))

- Log alert acknowledgements
  ([`dcd70ce`](https://github.com/tvallas/mqtt-alerts/commit/dcd70ce20c4f323c07cd97ab36dd3ca87786dbc2))


## v0.2.0 (2026-04-20)

### Chores

- **dev**: Ignore local testing files
  ([`b564672`](https://github.com/tvallas/mqtt-alerts/commit/b5646729ec898f89f130d6032a4c1a92ac6db107))

- **release**: 0.2.0
  ([`c1cc3fc`](https://github.com/tvallas/mqtt-alerts/commit/c1cc3fc048fb64977c7253e821d30fbe9081c68f))

### Features

- **runtime**: Reload config changes without restart
  ([`4a2ac9e`](https://github.com/tvallas/mqtt-alerts/commit/4a2ac9eab29f6b072ad3661f3f743fb628f64144))


## v0.1.0 (2026-04-20)

- Initial Release
