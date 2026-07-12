# Terms of Service

Effective date: July 11, 2026

These terms apply to Oura MCP Gateway, an open-source, locally operated software project. By using the software, you
agree to these terms and the [MIT License](LICENSE).

## Permitted use

You may use, copy, modify, and distribute the software as allowed by the MIT License. You must use it lawfully and only
with Oura accounts and data you are authorized to access. You are responsible for your OAuth application, credentials,
MCP host, downstream destinations, and compliance with Oura's terms and developer requirements.

Each user must supply and protect their own Oura developer application credentials. Maintainer credentials are not
shared. This local project does not support a hosted or multi-user OAuth service; operating one requires a separate
security, privacy, compliance, and deployment design.

## Health disclaimer

The software retrieves and transforms wellness data. It is not a medical device, does not provide medical advice, and
must not be used to diagnose, treat, cure, or prevent a disease or as a substitute for a qualified health professional.
Do not rely on it for emergencies or safety-critical decisions.

## Third-party services

Oura and any MCP host, AI provider, or other connected destination are independent third parties with their own
terms, availability, security, and privacy practices. The project maintainer does not control those services and is
not responsible for their behavior or changes to their APIs.

## Security and availability

You are responsible for protecting `.env`, OAuth tokens, local files, backups, and any data returned by the gateway.
The software may stop working because of configuration errors, expired authorization, upstream API changes, rate
limits, network failures, or defects. No uptime, support, data-completeness, or fitness guarantee is provided.

## Warranty and liability

The software is provided "as is" without warranty, to the maximum extent permitted by law. Liability is limited as set
out in the MIT License.

## Changes and contact

Changes will be published in this repository with an updated effective date. For non-sensitive questions, open an issue
at <https://github.com/whuang214/oura-mcp-gateway/issues>. Never post secrets or personal health data publicly.
