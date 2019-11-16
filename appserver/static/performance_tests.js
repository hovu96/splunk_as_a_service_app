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

    const launchButton = $('<button class="btn btn-primary action-button">Launch Test</button>');
    launchButton.click(async function () {
        window.location.href = 'performance_test_launch';
    });
    $(".dashboard-view-controls").append(launchButton);


});
