const appName = window.location.pathname.match(/..-..\/app\/(?<app>[^\/]+)/).groups.app;

require([
    "jquery",
    "/static/app/" + appName + "/modal.js",
    "/static/app/" + appName + "/utils.js",
    "splunkjs/mvc",
    'splunkjs/mvc/simplexml/ready!',
], function (
    $,
    Modal,
    Utils,
    mvc,
    _
) {
    var endpoint = Utils.createRestEndpoint();
    const titleElement = $(".dashboard-title.dashboard-header-title");
    const tokens = mvc.Components.getInstance("submitted");
    const bundleName = tokens.attributes.name;

    const initialTitle = titleElement.text();
    const updateTitle = function (title) {
        titleElement.text(initialTitle + ": " + title);
    };
    updateTitle(bundleName);

    const backButton = $('<button class="btn action-button">Back</button>');
    backButton.click(async function () {
        window.location.href = 'apps';
    });
    $(".dashboard-view-controls").append(backButton);
});
