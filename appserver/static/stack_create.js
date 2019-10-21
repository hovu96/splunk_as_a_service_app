const appName = window.location.pathname.match(/..-..\/app\/(?<app>[^\/]+)/).groups.app;

require([
    'jquery',
    'underscore',
    'backbone',
    'splunkjs/mvc',
    'views/shared/controls/StepWizardControl',
    "/static/app/" + appName + "/utils.js",
    'splunkjs/mvc/simplexml/ready!',
],
    function ($, _, Backbone, mvc, StepWizardControl, Utils) {
        var endpoint = Utils.createRestEndpoint();

        const steps = new Backbone.Collection([
            new Backbone.Model({
                value: "cluster",
                label: "Cluster",
            }), new Backbone.Model({
                value: "topology",
                label: "Topology",
            }), new Backbone.Model({
                value: "naming",
                label: "Naming",
            }), new Backbone.Model({
                value: "resources",
                label: "Resources",
            }), new Backbone.Model({
                value: "license",
                label: "License",
            }), new Backbone.Model({
                value: "summary",
                label: "Summary",
                showNextButton: false,
            })
        ]);

        const tokens = mvc.Components.getInstance('submitted');

        const loadingIndicator = Utils.newLoadingIndicator({
            title: "Loading Defaults ...",
            subtitle: "Please wait."
        });
        endpoint.get('configure', {}, function (err, response) {
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

        $(".option[name='cluster']").change(function () {
            const clusterName = $(this).attr('value');
            if (!clusterName) return;
            endpoint.get('cluster/' + clusterName, {}, function (err, response) {
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
                    const name = el.attr("name");
                    var value = response.data[name];
                    if (value) {
                        el.attr('value', value);
                    }
                });
            });
        });

        const setDeploymentOptionsAsTokens = function () {
            $('.deployment-options .option').each(function () {
                var el = $(this);
                var value = el.attr('value');
                if (!value) value = "";
                tokens.set("option_" + el.attr("name"), value);
            });
        };

        setDeploymentOptionsAsTokens();

        const wizardModel = new Backbone.Model({
            currentStep: "",
        });
        wizardModel.on('change:currentStep', function (model, currentStep) {
            steps.each(function (step) {
                const tokenName = "step-" + step.get("value");
                tokens.set(tokenName, undefined);
            });
            var step = steps.find(function (step) {
                return step.get('value') == currentStep;
            });
            const tokenName = "step-" + currentStep;
            tokens.set(tokenName, true);
            setDeploymentOptionsAsTokens();
        }.bind(this));
        wizardModel.set("currentStep", "cluster");

        const stepWizard = new StepWizardControl({
            model: wizardModel,
            modelAttribute: 'currentStep',
            collection: steps,
        });

        $('#step-control-wizard').append(stepWizard.render().el);

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
);