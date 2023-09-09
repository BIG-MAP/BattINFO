# Release a new BattINFO version

## Introduction

This document describes the process of releasing a new version of the BattINFO ontology.

## Prerequisites

To release a new version of the BattINFO ontology, you need to have:

- A GitHub account with release creation access to the [BattINFO repository](https://github.com/BIG-MAP/BattINFO).

## Release process

The release process is as follows:

1. [Create a new release on GitHub.](#create-a-new-release-on-github)
2. [Check that the documentation is built and published correctly.](#check-that-the-documentation-is-built-and-published-correctly)

### Create a new release on GitHub

To create a new release on GitHub, follow these steps:

1. Go to [create a new release in the BattINFO repository](https://github.com/BIG-MAP/BattINFO/releases/new).
2. Set the tag version to the version you want to release, e.g., `v0.1.0`.
3. Set the release title similarly, e.g., `v0.1.0`.
4. Write a description of the release.

### Check that the documentation is built and published correctly

To check that the documentation is built and published correctly, follow these steps:

1. Go to [the Actions tab in the BattINFO repository](https://github.com/BIG-MAP/BattINFO/actions).
2. Click on the latest workflow run for the "Publish new release" workflow.
3. Ensure it finishes successfully.

If the workflow run finishes successfully, the version will be updated in the `owl:versionIRI` and `owl:versionInfo` values of the [`battinfo.ttl`](../../battinfo.ttl) file as well as in the [`catalog-v001.xml`](../../catalog-v001.xml) file.
After these changes being merged back into the `master` branch, the documentation will be built and published to the `gh-pages` branch of the repository with the new version.
This will be done by calling the [`update_ghpages.yml`](../../.github/workflows/update_ghpages.yml) workflow.
