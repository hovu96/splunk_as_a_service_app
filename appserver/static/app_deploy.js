const appName = window.location.pathname.match(/..-..\/app\/(?<app>[^\/]+)/).groups.app;

require([
    "jquery",
    "/static/app/" + appName + "/jstree/jstree.min.js",
    "/static/app/" + appName + "/utils.js",
    "/static/app/" + appName + "/modal.js",
    'backbone',
    'splunkjs/mvc',
    'views/shared/controls/StepWizardControl',
    "splunkjs/ready!",
], function (
    $,
    _,
    Utils,
    Modal,
    Backbone,
    mvc,
    StepWizardControl,
    _
) {
    var endpoint = Utils.createRestEndpoint();
    const defaultTokens = mvc.Components.getInstance("default");
    const submittedTokens = mvc.Components.getInstance('submitted');

    if (defaultTokens.attributes.stack) {
        $('#stack-selected-info').show();
        $('#selected-stack').text(defaultTokens.attributes.stack);
    }
    if (defaultTokens.attributes.name) {
        $('#app-selected-info').show();
        $('#selected-app').text(defaultTokens.attributes.name);
    }
    if (defaultTokens.attributes.stack && defaultTokens.attributes.name && defaultTokens.attributes.version) {
        const progressIndicator = Utils.newLoadingIndicator({
            title: "Loading ...",
            subtitle: "Please wait.",
        });
        const path = 'stack_app/' + defaultTokens.attributes.stack + "/" + defaultTokens.attributes.name;
        endpoint.get(path, {}, async function (err, response) {
            progressIndicator.hide();
            if (err) {
                Utils.showErrorDialog("Error loading details", err).footer.append($('<button>Reload</button>').attr({
                    type: 'button',
                    class: "btn btn-primary",
                }).on('click', function () {
                    window.location.reload();
                }));
                return;
            }
            const stack = await Utils.getResponseContent(response);
            const deployTo = stack["deploy_to"];
            deployTo.forEach(function (role) {
                $(`.deployment-targets input[name=\"${role}\"]`).prop('checked', true);
            });
        });
    }

    const backButton = $('<button class="btn action-button">Back</button>');
    backButton.click(async function () {
        if (defaultTokens.attributes.stack && defaultTokens.attributes.name && defaultTokens.attributes.version) {
            window.location.href = 'stack_app?stack=' + defaultTokens.attributes.stack + "&name=" + encodeURIComponent(defaultTokens.attributes.name) + "&version=" + encodeURIComponent(defaultTokens.attributes.version) + "&back=stack";
        }
        else if (defaultTokens.attributes.stack) {
            window.location.href = 'stack?id=' + defaultTokens.attributes.stack;
        }
        else if (defaultTokens.attributes.name && defaultTokens.attributes.version) {
            window.location.href = "app?name=" + encodeURIComponent(defaultTokens.attributes.name) + "&version=" + encodeURIComponent(defaultTokens.attributes.version);
        }
    });
    $(".dashboard-view-controls").append(backButton);

    var stack;
    var app;
    const appOrStackChanged = async function () {

        const appValue = appOption.attr('value');
        if (!appValue) return;
        const comps = appValue.split(":")
        const appName = comps[0];
        const appVersion = comps[1];

        const stackID = stackOption.attr('value');
        if (!stackID) return;

        try {
            const appConfPromise = endpoint.getAsync('app_config/' + encodeURIComponent(appName) + "/" + encodeURIComponent(appVersion));
            const stackPromise = endpoint.getAsync('stack/' + stackID);
            const appPromise = endpoint.getAsync('app/' + encodeURIComponent(appName) + "/" + encodeURIComponent(appVersion));

            const appConfResponse = await appConfPromise;
            const stackResponse = await stackPromise;
            const appResponse = await appPromise;

            stack = await Utils.getResponseContent(stackResponse);
            app = await Utils.getResponseContent(appResponse);

            const deploymentType = stack["deployment_type"];
            if (deploymentType == "standalone") {
                $("splunk-control-group.distributed").hide();
                $("splunk-control-group.standalone").show();
            } else if (deploymentType == "distributed") {
                $("splunk-control-group.standalone").hide();
                $("splunk-control-group.distributed").show();
            } else {
                $("splunk-control-group.standalone").hide();
                $("splunk-control-group.distributed").hide();
                console.warn("unexpected deployment type: " + deploymentType);
            }

            if (defaultTokens.attributes.stack && defaultTokens.attributes.name && defaultTokens.attributes.version) {
            }
            else {
                $(".deployment-targets input[type=\"checkbox\"]").each(function () {
                    $(this).prop('checked', false);
                });
                if (deploymentType == "standalone") {
                    app["standalone_deploy_to"].forEach(function (role) {
                        $(`.deployment-targets input[name=\"${role}\"]`).prop('checked', true);
                    });
                } else if (deploymentType == "distributed") {
                    app["distributed_deploy_to"].forEach(function (role) {
                        $(`.deployment-targets input[name=\"${role}\"]`).prop('checked', true);
                    });
                }
            }

            const confNames = Object.keys(appConfResponse.data).sort();
            const defaultConfigTextArea = $('#default-config-content textarea');
            defaultConfigTextArea.attr("readonly", "readonly");
            $("#default-config-explorer").jstree('destroy');
            $('#default-config-explorer').jstree({
                core: {
                    'multiple': false,
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
                    defaultConfigTextArea.val("");
                } else {
                    const node = data.instance.get_node(data.selected[0]);
                    const confName = node.text;
                    const text = appConfResponse.data[confName];
                    defaultConfigTextArea.val(text);
                }
            });

        }
        catch (err) {
            Utils.showErrorDialog("Error Loading Details", err).footer.append($('<button>Reload</button>').attr({
                type: 'button',
                class: "btn btn-primary",
            }).on('click', function () {
                window.location.reload();
            }));
            return;
        }
    };

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
    stackOption.change(appOrStackChanged);

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
    appOption.change(appOrStackChanged);

    appOrStackChanged()

    const customConfig = {};
    const customConfigTextArea = $('#custom-config-content textarea');
    customConfigTextArea.attr("readonly", "readonly");
    const createDataFromCustomConfig = function () {
        return Object.keys(customConfig).sort().map(function (name) {
            return {
                text: name,
                icon: "jstree-file",
                id: name,
            }
        })
    };
    const customConfigExplorer = $('#custom-config-explorer').jstree({
        core: {
            'multiple': false,
            themes: {
                dots: false,
            },
            data: createDataFromCustomConfig(),
        }
    }).on('changed.jstree', function (e, data) {
        if (data.selected.length == 0) {
            customConfigTextArea.val("");
            customConfigTextArea.attr("readonly", "readonly");
        } else {
            customConfigTextArea.removeAttr("readonly");
            const node = data.instance.get_node(data.selected[0]);
            const confName = node.text;
            const text = customConfig[confName];
            customConfigTextArea.val(text);
        }
    });
    const updateCustomConfigExplorer = function () {
        customConfigExplorer.jstree(true).settings.core.data = createDataFromCustomConfig();
        customConfigExplorer.jstree(true).refresh();
    };
    $("#add-config-button").click(function () {
        const modal = new Modal(undefined, {
            title: 'Add Config',
            backdrop: 'static',
            keyboard: false,
            destroyOnHide: true,
            type: 'normal',
        });
        modal.body.append($(`
            <p>
                Enter the name of the config file to add:
            </p>
            <p>
                <input id="add-config-name" type="text" style="width: 100%;"></input>
            </p>
            `));
        modal.footer.append($('<button>Cancel</button>').attr({
            type: 'button',
            'data-dismiss': 'modal',
            class: "btn",
        }));
        modal.footer.append($('<button>Add</button>').attr({
            type: 'button',
            'data-dismiss': 'modal',
            class: "btn btn-primary",
        }).click(function () {
            var confName = $("#add-config-name").val();
            if (!confName.endsWith(".conf")) {
                confName += ".conf";
            }
            if (!customConfig[confName]) {
                customConfig[confName] = '';
            }
            updateCustomConfigExplorer();
            customConfigExplorer.jstree("deselect_all");
            customConfigExplorer.jstree().select_node(confName);
        }));
        modal.show();
        setTimeout(function () {
            $("#add-config-name").focus();
        }, 500);
    });
    customConfigTextArea.bind('input propertychange', function () {
        const confName = customConfigExplorer.jstree('get_selected');
        if (confName.length == 0) return;
        customConfig[confName] = this.value;
    });

    stepCollection.push(new Backbone.Model({
        value: "target",
        label: "Target",
        validate: function (selectedModel, isSteppingNext) {
            var promise = $.Deferred();
            if (!isSteppingNext) {
                promise.resolve();
                return promise;
            }
            const deploymentType = stack["deployment_type"];
            const targetLabels = [];
            $(".deployment-targets ." + deploymentType + " input[type=\"checkbox\"]").each(function () {
                const checkbox = $(this);
                if (checkbox.is(":checked")) {
                    const targetID = checkbox.attr("id");
                    const targetLabel = $(`label[for="${targetID}"]`).text();
                    targetLabels.push(targetLabel);
                }
            });
            if (targetLabels.length > 0) {
                $("#summary-selected-target").text(targetLabels.join(", "));
                promise.resolve();
                return promise;
            }
            Utils.showErrorDialog("Select Deployment Target", "Select the target Splunk roles to deploy the app to.", true);
            promise.reject();
            return promise;
        }
    }));

    stepCollection.push(new Backbone.Model({
        value: "config",
        label: "Config",
        validate: function (selectedModel, isSteppingNext) {
            var promise = $.Deferred();
            promise.resolve();
            $("#summary-custom-config").text(Object.keys(customConfig).join(", "));
            $("#summary-selected-app").text(appOption.attr("value"));
            $("#summary-selected-stack").text(stackOption.attr("value"));
            return promise;
        }
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

    $("#update-button").show().click(async function () {
        const deploymentType = stack["deployment_type"];
        const deployToNames = [];
        $(".deployment-targets ." + deploymentType + " input[type=\"checkbox\"]").each(function () {
            const checkbox = $(this);
            if (checkbox.is(":checked")) {
                const targetName = checkbox.attr("name");
                deployToNames.push(targetName);
            }
        });
        const options = {
            deploy_to: deployToNames.join(","),
        };
        if (defaultTokens.attributes.stack && defaultTokens.attributes.name) {
            try {
                const progressIndicator = Utils.newLoadingIndicator({
                    title: "Updating App ...",
                    subtitle: "Please wait.",
                });
                try {
                    const path = 'stack_app/' + defaultTokens.attributes.stack + "/" + defaultTokens.attributes.name;
                    await endpoint.postAsync(path, options);
                    window.location.href = 'stack_app?stack=' + encodeURIComponent(defaultTokens.attributes.stack) + "&name=" + encodeURIComponent(defaultTokens.attributes.name) + "&version=" + encodeURIComponent(defaultTokens.attributes.version) + "&back=stack";
                } finally {
                    progressIndicator.hide();
                }
            }
            catch (err) {
                await Utils.showErrorDialog(null, err, true).wait();
            }
        }
        else {
            const stackID = stackOption.attr("value");
            const appComps = appOption.attr("value").split(":")
            const appName = appComps[0];
            const appVersion = appComps[1];
            options["app_name"] = appName;
            options["app_version"] = appVersion;
            Object.keys(customConfig).forEach(function (confName) {
                const nameWithoutExtension = confName.split('.')[0];
                options["conf_" + nameWithoutExtension] = customConfig[confName];
            });
            try {
                const progressIndicator = Utils.newLoadingIndicator({
                    title: "Deploying App ...",
                    subtitle: "Please wait.",
                });
                try {
                    const path = 'stack_apps/' + stackID;
                    await endpoint.postAsync(path, options);
                    var back;
                    if (defaultTokens.attributes.stack) {
                        back = "stack";
                    }
                    else {
                        back = "app";
                    }
                    window.location.href = 'stack_app?stack=' + stackID + "&name=" + appName + "&version=" + appVersion + "&back=" + back;
                } finally {
                    progressIndicator.hide();
                }
            }
            catch (err) {
                await Utils.showErrorDialog(null, err, true).wait();
            }
        }
    });
});
