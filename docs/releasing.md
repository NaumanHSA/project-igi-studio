# Releasing

A release is built by GitHub Actions from a tag, never on a personal machine,
so what people download is exactly what the repository says.
[`.github/workflows/release.yml`](../.github/workflows/release.yml) does the
building; [`app/tools/release.js`](../app/tools/release.js) checks the versions
and writes the checksums and the notes.

## Cutting one

1. **The version, in both places.** The app and the studio carry it:

   ```
   cd app
   npm version 1.1.0 --no-git-tag-version     app/package.json and its lock file
   ```

   and `__version__` in `studio/__init__.py`.

2. **The notes.** Add a `## 1.1.0` section at the top of
   [`CHANGELOG.md`](../CHANGELOG.md). It becomes the release's notes on
   GitHub, followed by the download table, the checksums and, while releases
   are unsigned, the SmartScreen note.

3. **Check it.** `node app/tools/release.js check v1.1.0` says whether the
   versions and the changelog agree. The workflow runs the same check first
   and stops if they do not.

4. **A dry run, if the build changed.** Actions, Release, Run workflow (on
   `main`) builds everything and keeps it as the run's artifact without
   publishing anything.

5. **Tag and push.**

   ```
   git tag v1.1.0
   git push origin v1.1.0
   ```

   The workflow builds on Windows and drafts the release with the installer,
   the portable zip, `SHA256SUMS.txt`, and the two files installed studios
   update from: `latest.yml` and the installer's `.blockmap`.

6. **Publish.** Open the draft under Releases, read it, and press Publish.
   From that moment the site's download page offers it, and installed studios
   find it the next time they start.

A tag with a dash (`v1.1.0-beta.1`) makes a pre-release. The download page and
the studio's updates both skip pre-releases.

## Things not to do

- **Never reuse a version number**, even for a release that was deleted.
  Installed studios compare versions, and the updater caches by version.
- **Never rename or remove `latest.yml` or the installer from a published
  release.** That is how every installed studio finds and checks its update.
- **Never upload a file built by hand** to a release. Signing (below) only
  vouches for what the workflow built.

## Signing

Releases are unsigned until SignPath Foundation accepts the project; the
policy is on the site at `/signing`. Their conditions, in short: an open
source licence, a public repository, releases already out and built in CI,
multi-factor sign-in on GitHub and SignPath for everyone in the team, product
name and version on every signed file (the app and `studio-server.exe` both
carry them), and a manual approval for every release.

### Applying

At [signpath.org](https://signpath.org), once a release is published. The
answers the form asks for:

| | |
|---|---|
| Project | Project IGI Studio: a mission studio for *Project I.G.I.: I'm Going In* (2000). Design missions on a map of the game's levels, and the studio compiles and installs them into the user's own copy of the game. Windows desktop app (Electron, with a bundled Python server) |
| Repository | https://github.com/NaumanHSA/project-igi-studio |
| Licence | MIT, for all of it; third party parts are MIT or SIL OFL (`THIRD-PARTY-NOTICES.md`) |
| Downloads | https://naumanhsa.github.io/project-igi-studio-site/download, from the GitHub releases |
| Code signing policy | https://naumanhsa.github.io/project-igi-studio-site/signing |
| Build | GitHub Actions, `.github/workflows/release.yml`, from a tag |
| What to sign | The NSIS installer, and `Project IGI Studio.exe` and `studio-server.exe` inside it and the portable zip |
| Team | Nouman Ahsan (@NaumanHSA): author, reviewer and approver |

Before sending it: multi-factor sign-in on GitHub, and the repository's
Security tab with private vulnerability reporting turned on (`SECURITY.md`
and `CODE_OF_CONDUCT.md` point at it).

### Once accepted

The workflow changes like this:

1. After `npm run dist`, submit `app/dist/win-unpacked` and the installer to
   SignPath with their GitHub action (`signpath/github-action-submit-signing-request`),
   and wait for the approval.
2. Replace the unsigned files with the signed ones.
3. **Write `latest.yml` again.** Signing changes the installer's bytes, so its
   `sha512` and `size` must be recomputed from the signed file, and its
   `.blockmap` rebuilt. Otherwise every installed studio rejects the update as
   corrupt.
4. Run `assemble` with `SIGNED=1`, which leaves the SmartScreen note out of the
   release notes, and update the site's install page and download page, which
   mention it too.
