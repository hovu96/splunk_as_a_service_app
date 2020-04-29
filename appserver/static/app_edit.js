const appName = Splunk.util.getPath().match(`\/app\/(.+)\/.+`)[1];

require([
    "jquery",
    Splunk.util.make_url(`/static/app/${appName}/modal.js`),
    Splunk.util.make_url(`/static/app/${appName}/utils.js`),
    'backbone',
    'views/shared/controls/StepWizardControl',
    "splunkjs/mvc",
    'splunkjs/mvc/simplexml/ready!',
], function (
    $,
    Modal,
    Utils,
    Backbone,
    StepWizardControl,
    mvc,
    _
) {
    var endpoint = Utils.createRestEndpoint();
    const titleElement = $(".dashboard-title.dashboard-header-title");
    const submittedTokens = mvc.Components.getInstance("submitted");
    const appName = submittedTokens.attributes.name;
    const appVersion = submittedTokens.attributes.version;

    const initialTitle = titleElement.text();
    const updateTitle = function (title) {
        titleElement.text(initialTitle + ": " + title + " (" + appVersion + ")");
    };
    updateTitle(appName);

    const backButton = $('<button class="btn action-button">Back</button>');
    backButton.click(async function () {
        window.location.href = submittedTokens.attributes.back;
    });
    $(".dashboard-view-controls").append(backButton);

    const progressIndicator = Utils.newLoadingIndicator({
        title: "Loading ...",
        subtitle: "Please wait.",
    });
    const path = 'app/' + appName + "/" + encodeURIComponent(appVersion);
    endpoint.get(path, {}, async function (err, response) {
        progressIndicator.hide();
        if (err) {
            Utils.showErrorDialog("Error loading app details", err).footer.append($('<button>Reload</button>').attr({
                type: 'button',
                class: "btn btn-primary",
            }).on('click', function () {
                window.location.reload();
            }));
            return;
        }
        const app = await Utils.getResponseContent(response);
        app["standalone_deploy_to"].forEach(function (roleName) {
            const checkBox = $(".deployment_target .standalone .option[name=\"" + roleName + "\"]");
            checkBox.prop('checked', true);
        });
        app["distributed_deploy_to"].forEach(function (roleName) {
            const checkBox = $(".deployment_target .distributed .option[name=\"" + roleName + "\"]");
            checkBox.prop('checked', true);
        });
    });

    const stepCollection = [
        new Backbone.Model({
            value: "target",
            label: "Target",
            validate: function (selectedModel, isSteppingNext) {
                var promise = $.Deferred();
                promise.resolve();
                const distributedTargets = [];
                $(".deployment_target .distributed .option").each(function () {
                    const checkBox = $(this);
                    if (checkBox.is(':checked')) {
                        const id = checkBox.attr("id");
                        const roleTitle = $("label[for=\"" + id + "\"]").text();
                        distributedTargets.push(roleTitle);
                    }
                });
                $("#summary-selected-target-distributed").text(distributedTargets.join(", "));
                const standloneTargets = [];
                $(".deployment_target .standalone .option").each(function () {
                    const checkBox = $(this);
                    if (checkBox.is(':checked')) {
                        const id = checkBox.attr("id");
                        const roleTitle = $("label[for=\"" + id + "\"]").text();
                        standloneTargets.push(roleTitle);
                    }
                });
                $("#summary-selected-target-standalone").text(standloneTargets.join(",\n "));
                return promise;
            }
        }),
        new Backbone.Model({
            value: "summary",
            label: "Summary",
            showNextButton: false,
        }),
    ];

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

    $("#update-button").click(async function () {
        const distributed_targets = [];
        $(".deployment_target .distributed .option").each(function () {
            const checkBox = $(this);
            if (checkBox.is(':checked')) {
                const roleName = checkBox.attr("name");
                distributed_targets.push(roleName);
            }
        });
        const standalone_targets = [];
        $(".deployment_target .standalone .option").each(function () {
            const checkBox = $(this);
            if (checkBox.is(':checked')) {
                const roleName = checkBox.attr("name");
                standalone_targets.push(roleName);
            }
        });
        const options = {
            standalone_deploy_to: standalone_targets.join(", "),
            distributed_deploy_to: distributed_targets.join(", "),
        };
        try {
            const progressIndicator = Utils.newLoadingIndicator({
                title: "Updating App ...",
                subtitle: "Please wait.",
            });
            try {
                const path = 'app/' + encodeURIComponent(appName) + "/" + encodeURIComponent(appVersion);
                await endpoint.postAsync(path, options);
                window.location.href = submittedTokens.attributes.back;
            } finally {
                progressIndicator.hide();
            }
        }
        catch (err) {
            await Utils.showErrorDialog(null, err, true).wait();
        }
    });
});
