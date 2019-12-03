const appName = window.location.pathname.match(/..-..\/app\/(?<app>[^\/]+)/).groups.app;

require([
    "jquery",
    "/static/app/" + appName + "/jstree/jstree.js",
    "/static/app/" + appName + "/utils.js",
    'backbone',
    'splunkjs/mvc',
    'views/shared/controls/StepWizardControl',
    "splunkjs/ready!",
], function (
    $,
    jstree,
    Utils,
    Backbone,
    mvc,
    StepWizardControl,
    _
) {
    var endpoint = Utils.createRestEndpoint();
    const defaultTokens = mvc.Components.getInstance("default");
    const submittedTokens = mvc.Components.getInstance('submitted');

    const backButton = $('<button class="btn action-button">Back</button>');
    backButton.click(async function () {
        if (defaultTokens.attributes.stack) {
            window.location.href = 'stack?id=' + defaultTokens.attributes.stack;
        }
        else if (defaultTokens.attributes.name && defaultTokens.attributes.version) {
            window.location.href = "app?name=" + encodeURIComponent(defaultTokens.attributes.name) + "&version=" + encodeURIComponent(defaultTokens.attributes.version);
        }
    });
    $(".dashboard-view-controls").append(backButton);

    const stepCollection = [];

    const stackOption = $(".option[name='stack']");
    if (defaultTokens.attributes.stack) {
        stackOption.attr("value", defaultTokens.attributes.stack);
    } else {
        stepCollection.push(new Backbone.Model({
            value: "stack",
            label: "Stack",
            validate: function (selectedModel, isSteppingNext) {
                var promise = $.Deferred();
                if (!isSteppingNext) {
                    promise.resolve();
                    return promise;
                }
                const selectedStackID = stackOption.attr("value");
                if (selectedStackID) {
                    promise.resolve();
                } else {
                    Utils.showErrorDialog("Select Splunk Stack", "Select the target Splunk Stack to deploy the app to.", true);
                    promise.reject();
                }
                return promise;
            }
        }));
    }

    const appOption = $(".option[name='app']");
    if (defaultTokens.attributes.name && defaultTokens.attributes.version) {
        const app = defaultTokens.attributes.name + ":" + defaultTokens.attributes.version;
        appOption.attr("value", app);
    }
    else {
        stepCollection.push(new Backbone.Model({
            value: "app",
            label: "App",
            validate: function (selectedModel, isSteppingNext) {
                var promise = $.Deferred();
                if (!isSteppingNext) {
                    promise.resolve();
                    return promise;
                }
                const selectedApp = appOption.attr("value");
                if (selectedApp) {
                    promise.resolve();
                } else {
                    Utils.showErrorDialog("Select Splunk App", "Select the Splunk App to deploy to the Stack.", true);
                    promise.reject();
                }
                return promise;
            }
        }));
    }

    appOption.change(function () {
        const app = appOption.attr('value');
        if (!app) return;
        console.log(app);
        const comps = app.split(":")
        const appName = comps[0];
        const appVersion = comps[1];
        const path = 'app_config/' + encodeURIComponent(appName) + "/" + encodeURIComponent(appVersion);
        endpoint.get(path, {}, function (err, response) {
            if (err) {
                Utils.showErrorDialog("Error loading app contents", err).footer.append($('<button>Retry</button>').attr({
                    type: 'button',
                    class: "btn btn-primary",
                }).on('click', function () {
                    window.location.reload();
                }));
                return;
            }

            const textArea = $('#default-config-content textarea');
            const confNames = Object.keys(response.data).sort();
            $('#default-config-explorer').jstree({
                core: {
                    themes: {
                        dots: false,
                    },
                    data: confNames.map(function (name) {
                        return {
                            text: name,
                            icon: "jstree-file",
                            state: {
                                selected: name == confNames[0],
                            }
                        }
                    }),
                }
            }).on('changed.jstree', function (e, data) {
                if (data.selected.length == 0) {
                    textArea.attr("value", "");
                } else {
                    const node = data.instance.get_node(data.selected[0]);
                    const confName = node.text;
                    const text = response.data[confName];
                    textArea.text(text);
                }
            });
        });
    });
    appOption.change();

    $("#add-config-button").click(function () {

    });

    stepCollection.push(new Backbone.Model({
        value: "config",
        label: "Config",
    }));

    stepCollection.push(new Backbone.Model({
        value: "summary",
        label: "Summary",
        showNextButton: false,
    }));
    const steps = new Backbone.Collection(stepCollection);

    const wizardModel = new Backbone.Model({
        currentStep: "",
    });
    wizardModel.on('change:currentStep', function (model, currentStep) {
        steps.each(function (step) {
            const tokenName = "step-" + step.get("value");
            submittedTokens.set(tokenName, undefined);
        });
        var step = steps.find(function (step) {
            return step.get('value') == currentStep;
        });
        const tokenName = "step-" + currentStep;
        submittedTokens.set(tokenName, true);
    }.bind(this));
    wizardModel.set("currentStep", stepCollection[0].get("value"));

    const stepWizard = new StepWizardControl({
        model: wizardModel,
        modelAttribute: 'currentStep',
        collection: steps,
    });

    $('#step-control-wizard').append(stepWizard.render().el);

    $("#deploy-button").click(function () {
        alert("todo");
    });
});
