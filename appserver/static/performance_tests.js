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

    const launchButton = $('<button class="btn btn-primary action-button">Launch Test</button>');
    launchButton.click(async function () {
        window.location.href = 'performance_test_launch';
    });
    $(".dashboard-view-controls").append(launchButton);


});
