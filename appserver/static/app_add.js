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
    var endpoint = Utils.createRestEndpoint();

    $("#addButton").click(function () {
        const uploadURL = Splunk.util.make_url('custom', appName, "upload_app");

        const progressIndicator = Utils.newLoadingIndicator({
            title: "Adding App ...",
            subtitle: "Please wait."
        });

        $.ajax({
            url: uploadURL,
            type: 'POST',
            data: new FormData($('#upload-form')[0]),
            processData: false,
            contentType: false                    // Using FormData, no need to process data.
        }).done(function (app_name) {
            console.log(app_name);
            progressIndicator.hide();
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

        return;

        var options = {};
        $('.option').each(function () {
            var el = $(this);
            var value = el.attr('value');
            if (!value) value = "";
            options[el.attr("name")] = value;
        });

        let parameters = [...formData.entries()].map(e => encodeURIComponent(e[0]) + "=" + encodeURIComponent(e[1]))
        console.log(parameters);
        return;
        //$("#upload-form").post();

        endpoint.post(app_add, options, function (err, response) {
            if (err) {
                progressIndicator.hide();
                const dialog = Utils.showErrorDialog(null, err);
                dialog.footer.append($('<button>OK</button>').attr({
                    type: 'button',
                    'data-dismiss': 'modal',
                    class: "btn btn-primary",
                }));
                return;
            }
            window.location.href = 'apps';
        });
    });
});
