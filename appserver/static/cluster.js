const appName = Splunk.util.getPath().match(`\/app\/(.+)\/.+`)[1];

require([
    "jquery",
    Splunk.util.make_url(`/static/app/${appName}/modal.js`),
    Splunk.util.make_url(`/static/app/${appName}/utils.js`),
    "splunkjs/mvc",
    //"splunkjs/ready!",
    'splunkjs/mvc/simplexml/ready!',
], function (
    $,
    Modal,
    Utils,
    mvc,
    _
) {
    var endpoint = Utils.createRestEndpoint();
    const tokens = mvc.Components.getInstance("submitted");

    const clusterName = tokens.attributes.name;
    const titleElement = $(".dashboard-title.dashboard-header-title");
    if (clusterName) {
        $("splunk-text-input[name='name'] input").attr("disabled", "disabled");
        titleElement.text(titleElement.text() + ": " + clusterName);
        const loadingIndicator = Utils.newLoadingIndicator({
            title: "Loading Cluster Configuration ...",
            subtitle: "Please wait."
        });
        endpoint.get('cluster/' + clusterName, {}, function (err, response) {
            loadingIndicator.hide();
            if (err) {
                Utils.showErrorDialog(null, err).footer.append($('<button>Retry</button>').attr({
                    type: 'button',
                    class: "btn btn-primary",
                }).on('click', function () {
                    window.location.reload();
                }));
                return;
            }
            $('.option').each(function () {
                const el = $(this);
                const name = el.attr("name");
                var value = response.data[name];
                el.attr('value', value);
            });
        });
        const deleteButton = $('<button class="btn btn-primary action-button" style="background-color: red;">Delete</button>');
        deleteButton.click(function () {
            const modal = new Modal("delete-dialog-body", {
                title: 'Remove Cluster',
                backdrop: 'static',
                keyboard: false,
                destroyOnHide: true,
                type: 'normal',
            });
            modal.body.append($('<p>Removing a cluster will not stop Splunk stacks currently running. But it prevents this app from managing existing stacks as well as deploying new stacks.</p>'));
            modal.footer.append($('<button>Cancel</button>').attr({
                type: 'button',
                'data-dismiss': 'modal',
                class: "btn",
            }));
            modal.footer.append($('<button>Remove</button>').attr({
                type: 'button',
                'data-dismiss': 'modal',
                class: "btn btn-primary",
            }).css({
                "background-color": "red",
            }).click(async function () {
                const progressIndicator = Utils.newLoadingIndicator({
                    title: "Removing Cluster ...",
                    subtitle: "Please wait.",
                });
                try {
                    await endpoint.delAsync('cluster/' + clusterName);
                    progressIndicator.hide();
                    window.location.href = 'clusters';
                }
                catch (err) {
                    progressIndicator.hide();
                    await Utils.showErrorDialog(null, err, true).wait();
                }
            }));
            modal.show();
        });
        $(".dashboard-view-controls").append(deleteButton);
    } else {
        titleElement.text("Add " + titleElement.text());
        const loadingIndicator = Utils.newLoadingIndicator({
            title: "Loading Defaults ...",
            subtitle: "Please wait."
        });
        endpoint.get('cluster_defaults', {}, function (err, response) {
            loadingIndicator.hide();
            if (err) {
                Utils.showErrorDialog(null, err).footer.append($('<button>Retry</button>').attr({
                    type: 'button',
                    class: "btn btn-primary",
                }).on('click', function () {
                    window.location.reload();
                }));
                return;
            }
            $('.option').each(function () {
                const el = $(this);
                const name = el.attr("name");
                var value = response.data[name];
                if (name == "indexer_server" && !value) {
                    value = "" + window.location.hostname + ":9997";
                }
                if (name == "license_master_url" && !value) {
                    value = "https://" + window.location.hostname + ":8089";
                }
                el.attr('value', value);
            });
        });
    }

    $("#setupButton").click(function () {
        const progressIndicator = Utils.newLoadingIndicator({
            title: "Connecting to Kubernetes Cluster ...",
            subtitle: "Please wait."
        });

        var options = {};
        $('.option').each(function () {
            var el = $(this);
            var value = el.attr('value');
            if (!value) value = "";
            options[el.attr("name")] = value;
        });

        var saveEndpointName;
        if (clusterName) {
            saveEndpointName = "cluster/" + clusterName;
        } else {
            saveEndpointName = "clusters";
        }
        endpoint.post(saveEndpointName, options, function (err, response) {
            progressIndicator.hide();
            if (err) {
                const dialog = Utils.showErrorDialog(null, err);
                dialog.footer.append($('<button>OK</button>').attr({
                    type: 'button',
                    'data-dismiss': 'modal',
                    class: "btn btn-primary",
                }));
                return;
            }
            window.location.href = 'clusters';
        });
    });
});
