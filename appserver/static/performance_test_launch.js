const appName = Splunk.util.getPath().match(`\/app\/(.+)\/.+`)[1];

require([
    "jquery",
    'splunkjs/mvc',
    Splunk.util.make_url(`/static/app/${appName}/utils.js`),
    "splunkjs/ready!",
], function (
    $,
    mvc,
    Utils,
    _
) {
    var endpoint = Utils.createRestEndpoint();
    const tokens = mvc.Components.getInstance("submitted");

    const backButton = $('<button class="btn action-button">Back</button>');
    backButton.click(async function () {
        window.location.href = 'performance_tests';
    });
    $(".dashboard-view-controls").append(backButton);

    $("#run-button").click(async function () {
        try {
            var options = {
                testsuite: tokens.attributes.testsuite,
                run_duration: tokens.attributes.run_duration,
                cluster: tokens.attributes.cluster,
            };
            const progressIndicator = Utils.newLoadingIndicator({
                title: "Starting Performance Test ...",
                subtitle: "Please wait.",
            });
            try {
                const response = await endpoint.postAsync('performance_tests', options);
                const test = await Utils.getResponseContent(response);
                window.location.href = 'performance_test?test_id=' + test['test_id'];
            } finally {
                progressIndicator.hide();
            }
        }
        catch (err) {
            await Utils.showErrorDialog(null, err, true).wait();
        }
    });
});
