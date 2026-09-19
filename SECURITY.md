# Security

## Reporting a problem

Please do not open a public issue for a security problem. Report it privately
instead: on this repository's **Security** tab, choose **Report a
vulnerability**. You will get an answer, and credit when it is fixed if you
want it.

Things worth reporting:

- Anything that lets another program, or a web page, drive the studio. Its
  server answers only its own window, which carries a token made at each launch.
- Anything that makes the studio write outside the mission slots it created.
  Every write goes through `studio/protect.py`, which should refuse it.
- A way to read the AI designer's API key back out of the studio. It is kept
  encrypted for your Windows account, and the page never sees it again.
- A release file that does not match the checksum listed with its release, or
  that the [code signing policy](https://naumanhsa.github.io/project-igi-studio-site/signing)
  says should not exist.

## Supported versions

Only the latest release. An installed studio updates itself unless that is
turned off in Settings, Updates.
