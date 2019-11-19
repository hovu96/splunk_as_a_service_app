# Splunk as a Service App

A Splunk app to deploy, manage and monitor other Splunk environments in remote Kubernetes clusters.

![Service-Overview](ServiceOverview.png)

This is an early prototype and should not be used in a production environment.

## Features

- Managing any number of Splunk environments
- REST endpoints for integrating into service portals
- Activity tracking
- Changeback analytics
- App management
- Health tracking
- Capacity monitoring
- Performance testing

## Prerequisites

- Splunk Enterprise 8.0+ (to run this app)
- One or more Kubernetes Clusters 1.12+ (being the deployment targets)
- [Splunk Operator for Kubernetes](https://github.com/splunk/splunk-operator)
- [Splunk Connect for Kubernetes](https://github.com/splunk/splunk-connect-for-kubernetes)

## Getting Started

TODO

## Architecture

![Architecture](architecture.png)

## Contributing

Clone and create pull requests.

## Support

This app is not supported by Splunk Support. File issues [here](https://github.com/hovu96/splunk_as_a_service_app/issues/new).

## License

Apache License 2.0.

See [LICENSE](LICENSE).