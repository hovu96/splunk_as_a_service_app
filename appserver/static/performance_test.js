const appName = window.location.pathname.match(/..-..\/app\/(?<app>[^\/]+)/).groups.app;

require([
    "jquery",
    "/static/app/" + appName + "/utils.js",
    "splunkjs/mvc",
    "splunkjs/ready!"
], function (
    $,
    Utils,
    mvc,
    _
) {
    var endpoint = Utils.createRestEndpoint();
    const tokens = mvc.Components.getInstance("submitted");
    const testID = tokens.attributes.test_id;

    const titleElement = $(".dashboard-title.dashboard-header-title");
    titleElement.text(titleElement.text() + ": " + testID);

    const stopButton = $('<button class="btn btn-primary action-button" style="background-color: red;">Stop</button>');
    stopButton.click(async function () {
        const progressIndicator = Utils.newLoadingIndicator({
            title: "Stopping Performance Test ...",
            subtitle: "Please wait.",
        });
        try {
            await endpoint.delAsync('performance_test/' + testID, {
            });
            progressIndicator.hide();
            window.location.href = 'performance_tests';
        }
        catch (err) {
            progressIndicator.hide();
            await Utils.showErrorDialog(null, err, true).wait();
        }
    });
    $(".dashboard-view-controls").append(stopButton);

});