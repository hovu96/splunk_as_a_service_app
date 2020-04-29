const appName = Splunk.util.getPath().match(`\/app\/(.+)\/.+`)[1];

require([
    'jquery',
    'underscore',
    'backbone',
    'splunkjs/mvc',
    Splunk.util.make_url(`/static/app/${appName}/utils.js`),
    Splunk.util.make_url(`/static/app/${appName}/name_generator.js`),
    Splunk.util.make_url(`/static/app/${appName}/utils/wizard.js`),
    'splunkjs/mvc/simplexml/ready!',
],
    function ($, _, Backbone, mvc, Utils, NameGenerator, Wizard) {
        var endpoint = Utils.createRestEndpoint();

        const loadingIndicator = Utils.newLoadingIndicator({
            title: "Loading Defaults ...",
            subtitle: "Please wait."
        });
        endpoint.get('settings', {}, function (err, response) {
            loadingIndicator.hide();
            if (err) {
                Utils.showErrorDialog(null, err).footer.append($('<button>Retry</button>').attr({
                    type: 'button',
                    class: "btn btn-primary",
                }).on('click', function () {
                    window.location.reload();
                }));
                return;
            }
            $('.option').each(function () {
                const el = $(this);
                const name = "default_" + el.attr("name");
                var value = response.data[name];
                if (value) {
                    el.attr('value', value);
                }
            });
        });

        Wizard.create({
            element: "#create-stack-wizard",
            steps: [{
                value: "cluster",
                label: "Cluster",
                initialize: function () {
                    $(".option[name='cluster']").change(function () {
                        const clusterOption = $(this);
                        const clusterName = clusterOption.attr('value');
                        if (!clusterName) return;
                        endpoint.get('cluster/' + clusterName, {}, function (err, response) {
                            if (err) {
                                console.log(err);
                                if (err.status == 404) {
                                    clusterOption.attr('value', '');
                                    return
                                }
                                Utils.showErrorDialog(null, err).footer.append($('<button>Retry</button>').attr({
                                    type: 'button',
                                    class: "btn btn-primary",
                                }).on('click', function () {
                                    window.location.reload();
                                }));
                                return;
                            }
                            $('.option').each(function () {
                                const el = $(this);
                                const name = el.attr("name");
                                var value = response.data[name];
                                if (value) {
                                    el.attr('value', value);
                                }
                            });
                        });
                        $("#summary-cluster").text(Utils.capitalize(clusterName));
                    });
                },
            }, {
                value: "topology",
                label: "Topology",
                disappeared: function () {
                    const deploymentType = $(".option[name=\"deployment_type\"]").attr('value');
                    $("#summary-topology").text(Utils.capitalize(deploymentType));
                },
            }, {
                value: "naming",
                label: "Naming",
                appeared: function () {
                    const textBox = $("#stack-name-text-input");
                    if (textBox.attr("value") == "") {
                        const capitalize = function (s) {
                            return s.replace(/(?:^|\s)\S/g, function (a) { return a.toUpperCase(); });
                        };
                        const stackName = capitalize(NameGenerator.run(" "));
                        textBox.attr("value", stackName);
                    }
                    $("input", textBox).focus();
                }
            }, {
                value: "resources",
                label: "Resources",
            }, {
                value: "license",
                label: "License",
            }, {
                value: "summary",
                label: "Summary",
                showNextButton: false,
                initialize: function () {
                    $("#deploy-button").click(async function () {
                        var options = {};
                        $('.deployment-options .option').each(function () {
                            var el = $(this);
                            var value = el.attr('value');
                            if (!value) value = "";
                            options[el.attr("name")] = value;
                        });
                        try {
                            const progressIndicator = Utils.newLoadingIndicator({
                                title: "Deploying Stack ...",
                                subtitle: "Please wait.",
                            });
                            try {
                                const response = await endpoint.postAsync('stacks', options);
                                const stack = await Utils.getResponseContent(response);
                                window.location.href = 'stack?id=' + stack['stack_id'];
                            } finally {
                                progressIndicator.hide();
                            }
                        }
                        catch (err) {
                            await Utils.showErrorDialog(null, err, true).wait();
                        }
                    });
                }
            }],
        });
    }
);