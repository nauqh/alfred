# Changelog

All notable changes to the household are recorded here, sir - one keeps the master informed.

## [Unreleased]

### Added

- The week's report, posted each Sunday morning - the repertoire, the tally, the master of the queue

### Changed

- The player card now shows timestamped progress, source metadata, requesters and clearer empty states
- Queue panels show total duration and identify expired views as snapshots
- Search suggestions now label tracks, artists, albums and playlists directly
- Play history now records who queued each track, not merely an id. Older records carry over intact

### Fixed

- `/remove` now uses the same one-based track numbering shown in autocomplete

## [2.0.0] - 2026-08-29

### Added

- Queue pagination - ten tracks a page, Prev and Next included
- A progress bar that keeps its own time
- The now playing card, with Pause, Skip and Loop at your service
- Whoever queued the track may press its buttons
- @mentions answered, with command tool calling
- The track's name shown in the sidebar while playing
- A self-hosted YouTube cipher server
- This log posted to the channel upon restart

### Fixed

- Failed or stuck tracks no longer replay in a loop
