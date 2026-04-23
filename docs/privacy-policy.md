# Privacy Policy

Last updated: 2026-04-24

## Overview

Local Health Assistant is a local-first personal health assistant project. It combines user-provided food, hunger, and weight logs with Oura data and optional baseline health information to generate daily reviews and personalized recommendations.

This project is designed for personal use and local operation by default.

## Data We Use

Depending on the features enabled by the user, the application may process:

- Oura account data authorized by the user, such as daily sleep, readiness, and activity summaries
- user-entered food, hunger, and weight records
- user-defined goals
- optional baseline health details or report summaries

## How Data Is Used

The data is used to:

- store structured personal health records
- generate daily reviews
- provide personalized recommendations
- identify behavior patterns such as hunger triggers, tracking gaps, or recovery-related appetite risk

## Storage

By default, this project stores data locally on the user's device or self-managed environment, including:

- SQLite databases
- Markdown review files
- JSON snapshots of Oura responses

The project does not require sending data to third-party model providers in version 1.

## Sharing

This project does not intentionally share personal health data with third parties except where the user explicitly connects an external service, such as Oura, for authorized data access.

## Retention And Deletion

The user controls the local files and database and may delete them at any time. OAuth tokens and synced data should be treated as sensitive local data.

## Security

Reasonable efforts should be made by the operator to protect local credentials, OAuth secrets, and health data, including:

- using local-only configuration files
- avoiding committing secrets to version control
- restricting machine and filesystem access

## Contact

For questions about this project, contact the project operator using the contact details supplied in the related Oura application registration.
