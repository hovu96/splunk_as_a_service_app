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
    const backButton = $('<button class="btn action-button">Back</button>');
    backButton.click(async function () {
        window.location.href = 'apps';
    });
    $(".dashboard-view-controls").append(backButton);

    $("#addButton").click(function () {
        var uploadURL = Splunk.util.make_url('custom', appName, "upload_app", "post");
        const progressIndicator = Utils.newLoadingIndicator({
            title: "Uploading App...",
            subtitle: "Please wait."
        });
        const formData = new FormData($('#upload-form')[0])
        //var appFile = formData.get('app');
        //console.log(appFile.name);
        $.ajax({
            url: uploadURL,
            type: 'POST',
            data: formData,
            processData: false,
            contentType: false
        }).done(function (app) {
            console.log(app);
            if (app.kind == "app") {
                window.location.href = "app?name=" + encodeURIComponent(app.name) + "&version=" + encodeURIComponent(app.version);
            }
            else if (app.kind == "bundle") {
                window.location.href = "app_bundle?name=" + encodeURIComponent(app.name);
            }
            else {
                progressIndicator.hide();
                alert("TODO: implement browser redirect");
            }
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
