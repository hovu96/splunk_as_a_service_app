
define([
    'backbone',
    'splunkjs/mvc',
    'views/shared/controls/StepWizardControl',
    "../modal.js"
], function (Backbone, mvc, StepWizardControl, Modal) {
    const tokens = mvc.Components.getInstance('submitted');

    return function () {
        return {
            create: function (options) {
                const steps = new Backbone.Collection(options.steps.map(function (step) {
                    return new Backbone.Model(step);
                }));

                steps.each(function (step) {
                    const initializeFunc = step.get("initialize");
                    if (initializeFunc) {
                        initializeFunc();
                    }
                });

                const wizardModel = new Backbone.Model({
                    currentStep: "",
                });
                wizardModel.on('change:currentStep', function (model, currentStepName) {
                    const previousStepName = wizardModel.previous("currentStep")

                    steps.each(function (step) {
                        const tokenName = "step-" + step.get("value");
                        tokens.set(tokenName, undefined);
                    });
                    const tokenName = "step-" + currentStepName;
                    tokens.set(tokenName, true);

                    if (previousStepName) {
                        const previousStep = steps.find(function (step) {
                            return step.get("value") == previousStepName;
                        });
                        const disappearedFunc = previousStep.get("disappeared");
                        if (disappearedFunc) {
                            disappearedFunc();
                        }
                    }

                    const currentStep = steps.find(function (step) {
                        return step.get("value") == currentStepName;
                    });
                    const appearedFunc = currentStep.get("appeared");
                    if (appearedFunc) {
                        appearedFunc();
                    }
                }.bind(this));
                const firstStepName = steps.at(0).get("value")
                wizardModel.set("currentStep", firstStepName);

                const stepWizard = new StepWizardControl({
                    model: wizardModel,
                    modelAttribute: 'currentStep',
                    collection: steps,
                });

                $(options.element).append(stepWizard.render().el);

                return {

                };
            },
        };
    }();
});