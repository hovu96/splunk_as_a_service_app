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
    const appName = tokens.attributes.name;
    const appVersion = tokens.attributes.version;

    const initialTitle = titleElement.text();
    const updateTitle = function (title) {
        titleElement.text(initialTitle + ": " + title + " (" + appVersion + ")");
    };
    updateTitle(appName);

    endpoint.get('app/' + appName + "/" + appVersion, {}, function (err, response) {
        if (err) {
            Utils.showErrorDialog("Error loading app details", err).footer.append($('<button>Retry</button>').attr({
                type: 'button',
                class: "btn btn-primary",
            }).on('click', function () {
                window.location.reload();
            }));
            return;
        }
        updateTitle(response.data.title);
    });
});
