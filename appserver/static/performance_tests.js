const appName = window.location.pathname.match(/..-..\/app\/(?<app>[^\/]+)/).groups.app;

require([
    "jquery",
    'splunkjs/mvc',
    "/static/app/" + appName + "/utils.js",
    "splunkjs/ready!",
], function (
    $,
    mvc,
    Utils,
    _
) {
    var endpoint = Utils.createRestEndpoint();
    const tokens = mvc.Components.getInstance("submitted");

    $("#run-button").click(async function () {
        try {
            var options = {
                testsuite: tokens.attributes.testsuite,
            };
            $('.performance-test-options .option').each(function () {
                var el = $(this);
                var value = el.attr('value');
                if (!value) value = "";
                options[el.attr("name")] = value;
            });
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
