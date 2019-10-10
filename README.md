# Splunk as a Service App

A Splunk app to deploy, manage and monitor other Splunk environments in remote Kubernetes clusters.

This is an early prototype and should not be used in a production environment.

## Features

- Managing any number of Splunk environments
- REST endpoints for integrating into service portals
- Activity tracking
- Changeback analytics
- App management
- Health tracking
- Capacity monitoring

## Prerequisites

- Splunk Enterprise (to run this app)
- Once or more Kubernetes Clusters (being the deployment targets)
- Splunk Operator for Kubernetes (see [blog post](https://www.splunk.com/blog/2019/05/08/an-insider-s-guide-to-splunk-on-containers-and-kubernetes.html))
- [Splunk Connect for Kubernetes](https://github.com/splunk/splunk-connect-for-kubernetes)

## Getting Started

TODO

## Architecture

![Image of Yaktocat](architecture.png)

## Contributing

Clone and create pull requests.

## Support

This app is not supported by Splunk Support. File issues [here](https://github.com/hovu96/splunk_as_a_service_app/issues/new).

## License

Apache License 2.0.

See [LICENSE](LICENSE).