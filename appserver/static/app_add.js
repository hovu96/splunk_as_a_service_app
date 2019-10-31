const appName = window.location.pathname.match(/..-..\/app\/(?<app>[^\/]+)/).groups.app;

require([
    "jquery",
    "/static/app/" + appName + "/utils.js",
    "splunkjs/ready!",
], function (
    $,
    Utils,
    _
) {
    $("#addButton").click(function () {
        const uploadURL = Splunk.util.make_url('custom', appName, "upload_app");
        const progressIndicator = Utils.newLoadingIndicator({
            title: "Uploading App...",
            subtitle: "Please wait."
        });
        $.ajax({
            url: uploadURL,
            type: 'POST',
            data: new FormData($('#upload-form')[0]),
            processData: false,
            contentType: false
        }).done(function (app) {
            console.log(app);
            window.location.href = "app?name=" + encodeURIComponent(app.name) + "&version=" + encodeURIComponent(app.version);
        }).fail(function (xhr) {
            progressIndicator.hide();
            const dialog = Utils.showErrorDialog(null, xhr.responseText);
            dialog.footer.append($('<button>OK</button>').attr({
                type: 'button',
                'data-dismiss': 'modal',
                class: "btn btn-primary",
            }));
            return;
        });
    });
});
